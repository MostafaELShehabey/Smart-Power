"""Purchase orders (SP-82, P1/P2): where the goods go, in which batches, and how far they have come.

    destination   Main store, Showroom or Site sets each row's warehouse; Site uses the site
                  warehouse of the row's station, so one order can serve several stations
    batches       the rows of a batch share a delivery date; each row has its own price
    status        Draft, Sent, Partly received, Received, Closed or Cancelled, from ERPNext's own
                  status and received percent

There is no approval step: submitting sends the order, and the admin reviews afterwards. Most orders
start as drafts from the confirmed deposit (SP-175). A consignment conversion (SP-92) sets its own
warehouse. Supplier prices sit at the cost permlevel (SP-35).
"""

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.utils import cint, flt, getdate

from smart_power.sp_stock.warehouses import MAIN, SHOWROOM, SITE, site_warehouse, warehouse_of

STATION = "SP Station"
MANUAL = "Manual"
MAIN_STORE, SHOWROOM_STORE, SITE_DELIVERY = "Main store", "Showroom", "Site"
DRAFT, SENT, PARTLY, RECEIVED, CLOSED, CANCELLED = (
	"Draft",
	"Sent",
	"Partly received",
	"Received",
	"Closed",
	"Cancelled",
)
OPEN_STATUSES = (SENT, PARTLY)
FULL = 100  # sp-allow-number: ERPNext's received percent
STORE_TYPES = {MAIN_STORE: MAIN, SHOWROOM_STORE: SHOWROOM}
DESTINATION_OF = {MAIN: MAIN_STORE, SHOWROOM: SHOWROOM_STORE, SITE: SITE_DELIVERY}


class PurchaseOrderStatus:
	def set_status(self, update=False, status=None, update_modified=True):
		"""Every change of ERPNext's status, a receipt's included, moves the Smart Power status."""
		super().set_status(update=update, status=status, update_modified=update_modified)
		refresh_progress(self, update)


def enable_batches() -> None:
	"""One item can come in several batches, so an order can list it more than once."""
	frappe.db.set_single_value("Buying Settings", "allow_multiple_items", 1)


def status_of(doc) -> str:
	if doc.docstatus == DocStatus.draft():
		return DRAFT
	if doc.docstatus == DocStatus.cancelled():
		return CANCELLED
	if doc.status == CLOSED:
		return CLOSED
	received = flt(doc.per_received)
	if received >= FULL:
		return RECEIVED
	return PARTLY if received > 0 else SENT


def next_delivery(doc):
	"""The earliest batch date with something still to arrive, on an order that is still open."""
	if status_of(doc) in (RECEIVED, CLOSED, CANCELLED):
		return None
	dates = [
		getdate(r.schedule_date) for r in doc.items if r.schedule_date and flt(r.received_qty) < flt(r.qty)
	]
	return min(dates) if dates else None


def refresh_progress(doc, update: bool = False) -> None:
	values = {"sp_status": status_of(doc), "sp_next_delivery": next_delivery(doc)}
	doc.update(values)
	if update:
		doc.db_set(values, update_modified=False)


def _project(station: str | None) -> str | None:
	return frappe.db.get_value(STATION, station, "project") if station else None


def _store(company: str, destination: str) -> str:
	warehouse = warehouse_of(company, STORE_TYPES[destination])
	if not warehouse:
		frappe.throw(_("Company {0} has no {1} warehouse.").format(company, _(destination)))
	return warehouse


def _infer_destination(doc) -> str | None:
	"""An order made elsewhere, such as from the deposit, names its destination by its warehouse."""
	warehouse = doc.get("set_warehouse") or next((r.warehouse for r in doc.items if r.warehouse), None)
	kind = frappe.db.get_value("Warehouse", warehouse, "warehouse_type") if warehouse else None
	return DESTINATION_OF.get(kind)


def set_destination(doc) -> None:
	destination = doc.get("sp_destination_type") or _infer_destination(doc)
	doc.sp_destination_type = destination
	if doc.get("sp_station"):
		doc.project = _project(doc.sp_station)
	if not destination:
		return
	warehouses = set()
	for row in doc.items:
		row.sp_station = row.get("sp_station") or doc.get("sp_station")
		project = _project(row.sp_station)
		if project:
			row.project = project
		if destination == SITE_DELIVERY:
			if not project:
				frappe.throw(_("Row {0}: a delivery to site needs a station.").format(row.idx))
			row.warehouse = site_warehouse(project)
		else:
			row.warehouse = _store(doc.company, destination)
		warehouses.add(row.warehouse)
	doc.set_warehouse = warehouses.pop() if len(warehouses) == 1 else None


def set_batches(doc) -> None:
	"""Each batch arrives on one date; the order's own date is its first delivery."""
	dates = {}
	for row in doc.items:
		row.sp_batch_no = cint(row.get("sp_batch_no")) or 1
		row.schedule_date = row.schedule_date or doc.schedule_date
		if not row.schedule_date:
			continue
		date = getdate(row.schedule_date)
		if dates.setdefault(row.sp_batch_no, date) != date:
			frappe.throw(
				_("Batch {0} has two delivery dates. Give each date its own batch.").format(row.sp_batch_no),
				title=_("Check the batches"),
			)
	if dates:
		doc.schedule_date = min(dates.values())


def before_validate(doc, method=None) -> None:
	"""Purchase Order before_validate: the warehouses and dates ERPNext then checks."""
	set_batches(doc)
	if doc.get("sp_is_consignment_conversion"):
		return
	doc.sp_source = doc.get("sp_source") or MANUAL
	set_destination(doc)


def validate(doc, method=None) -> None:
	refresh_progress(doc)


def on_change(doc, method=None) -> None:
	"""Purchase Order on_submit and on_cancel."""
	refresh_progress(doc, update=True)


def on_receipt_change(doc, method=None) -> None:
	"""Purchase Receipt on_submit and on_cancel: the orders it received against move on."""
	for name in {row.purchase_order for row in doc.items if row.get("purchase_order")}:
		refresh_progress(frappe.get_doc("Purchase Order", name), update=True)
