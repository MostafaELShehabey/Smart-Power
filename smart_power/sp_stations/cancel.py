"""Cancel a station after the deposit (SP-176; decisions 60 and 71; ERD 7.2 Cancel Line).

The admin cancels a station before its technical close, with a reason:

    cancel_preview(station)                            what the cancel dialog shows
    cancel_station(station, reason, accounts, fates)   do it

- **Refunds** (owner, 2026-11-21): every confirmed customer payment on the station is refunded in
  full, each as a Payment Entry (Pay) from the account that received it, linked by sp_refund_of
  and pending the admin's confirmation in the confirmations centre (A1). A payment received
  into a person's transit cash refunds from an official account the admin picks (accounts:
  {payment entry: account}).
- **Stock and buying:** the contract's stock reservations are cancelled, draft purchase orders of
  the station are deleted, and submitted ones are flagged to the projects manager.
- **Cancel Lines:** what is at the site, one line per item with its fate (fates: {item: fate}).
  To stock (the default) moves it back to the main store at cost; Return to supplier makes a
  Purchase Return against the receipt that brought it for the station.
- The station becomes Cancelled with cancelled_on, the refund amount and the reason; the case is
  closed (Lost, "Cancelled after deposit") and the Sales Order is closed; the Review centre lists
  the cancellation.
"""

import frappe
from frappe import _
from frappe.utils import flt, today

from smart_power.sp_stations.station import is_admin
from smart_power.sp_stations.station_workflow import CANCELLED, FIN_CLOSED, TECH_CLOSED

STATION, ENTRY, PO, RECEIPT, STOCK_ENTRY = (
	"SP Station",
	"Payment Entry",
	"Purchase Order",
	"Purchase Receipt",
	"Stock Entry",
)
TO_STOCK, TO_SUPPLIER = "To stock", "Return to supplier"
FATES = (TO_STOCK, TO_SUPPLIER)
OFFICIAL = "Official"
PENDING = "Pending"
CASE, LOST, LOST_REASON = "SP Case", "Lost", ("Lost Reason", "CANCELLED_AFTER_DEPOSIT")
PM_ROLE = "SP Project Manager"


def _check(doc) -> None:
	if not is_admin():
		frappe.throw(_("Only the admin cancels a station."), frappe.PermissionError)
	if doc.status in (TECH_CLOSED, FIN_CLOSED, CANCELLED):
		frappe.throw(
			_("Station {0} is {1}; only a station before its technical close is cancelled.").format(
				doc.name, _(doc.status)
			)
		)


# --- what is refunded ----------------------------------------------------------------------------


def received(doc) -> list[dict]:
	"""The confirmed customer payments on the station, with the account each came into."""
	if not doc.project:
		return []
	rows = frappe.get_all(
		ENTRY,
		{"project": doc.project, "docstatus": 1, "payment_type": "Receive", "party_type": "Customer"},
		["name", "posting_date", "paid_amount", "paid_to", "mode_of_payment", "sp_is_deposit"],
		order_by="posting_date asc, creation asc",
	)
	refunded = set(
		frappe.get_all(ENTRY, {"sp_refund_of": ("in", [r.name for r in rows] or [""])}, pluck="sp_refund_of")
	)
	kinds = dict(
		frappe.get_all(
			"Account",
			{"name": ("in", list({r.paid_to for r in rows}) or [""])},
			["name", "sp_account_kind"],
			as_list=True,
		)
	)
	return [
		{
			"payment": r.name,
			"date": r.posting_date,
			"amount": flt(r.paid_amount),
			"account": r.paid_to,
			"official": kinds.get(r.paid_to) == OFFICIAL,
			"mode": r.mode_of_payment,
			"is_deposit": r.sp_is_deposit,
		}
		for r in rows
		if r.name not in refunded
	]


def official_accounts(company: str) -> list[str]:
	from smart_power.sp_finance.supplier_payment import official_accounts

	return official_accounts(company)


# --- what is at the site -------------------------------------------------------------------------


def site_lines(doc) -> list[dict]:
	"""One line per item in the station's site warehouse, with the receipt it could go back on."""
	if not doc.site_warehouse:
		return []
	bins = frappe.get_all(
		"Bin",
		{"warehouse": doc.site_warehouse, "actual_qty": (">", 0)},
		["item_code", "actual_qty"],
		order_by="item_code asc",
	)
	names = dict(
		frappe.get_all(
			"Item", {"name": ("in", [b.item_code for b in bins] or [""])}, ["name", "item_name"], as_list=True
		)
	)
	return [
		{
			"item_code": b.item_code,
			"item_name": names.get(b.item_code) or b.item_code,
			"qty": flt(b.actual_qty),
			"warehouse": doc.site_warehouse,
			"purchase_receipt": _receipt_for(doc, b.item_code),
		}
		for b in bins
	]


def _receipt_for(doc, item_code: str) -> str | None:
	"""The latest submitted receipt that brought this item for the station."""
	orders = frappe.get_all(PO, {"sp_station": doc.name, "docstatus": 1}, pluck="name")
	if not orders:
		return None
	rows = frappe.get_all(
		"Purchase Receipt Item",
		{"item_code": item_code, "purchase_order": ("in", orders), "docstatus": 1},
		["parent"],
		order_by="creation desc",
		limit=1,
	)
	if not rows or frappe.db.get_value(RECEIPT, rows[0].parent, "is_return"):
		return None
	return rows[0].parent


@frappe.whitelist()
def cancel_preview(station: str) -> dict:
	"""For the cancel dialog: the refunds, the official accounts, the site lines and the orders."""
	doc = frappe.get_doc(STATION, station)
	_check(doc)
	return {
		"refunds": received(doc),
		"accounts": official_accounts(doc.company),
		"lines": site_lines(doc),
		"draft_orders": frappe.get_all(PO, {"sp_station": doc.name, "docstatus": 0}, pluck="name"),
		"submitted_orders": frappe.get_all(PO, {"sp_station": doc.name, "docstatus": 1}, pluck="name"),
	}


# --- cancel ----------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def cancel_station(
	station: str, reason: str, accounts: str | dict | None = None, fates: str | dict | None = None
) -> dict:
	"""Cancel the station: refunds pending confirmation, reservations released, orders handled,
	the site's goods back to stock or to the supplier. Returns what was done."""
	doc = frappe.get_doc(STATION, station)
	_check(doc)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is needed to cancel the station."), frappe.MandatoryError)
	accounts = frappe.parse_json(accounts) or {}
	fates = frappe.parse_json(fates) or {}
	refunds = received(doc)
	allowed = set(official_accounts(doc.company))
	for row in refunds:
		chosen = row["account"] if row["official"] else accounts.get(row["payment"])
		if chosen not in allowed:
			frappe.throw(
				_("Choose the official account that refunds {0} received on {1}.").format(
					frappe.format(row["amount"], "Currency"), frappe.format(row["date"], "Date")
				),
				frappe.MandatoryError,
			)
		row["refund_from"] = chosen
	lines = site_lines(doc)
	for line in lines:
		line["fate"] = fates.get(line["item_code"]) or TO_STOCK
		if line["fate"] not in FATES:
			frappe.throw(_("Unknown fate {0}.").format(frappe.bold(line["fate"])))
		if line["fate"] == TO_SUPPLIER and not line["purchase_receipt"]:
			frappe.throw(
				_("{0} came with no receipt of this station; it can only go back to stock.").format(
					frappe.bold(line["item_name"])
				)
			)

	refund_entries = [_refund(doc, row) for row in refunds]
	_release_reservations(doc)
	deleted, flagged = _orders(doc, reason)
	for line in lines:
		if line["fate"] == TO_STOCK:
			line["stock_entry"] = _back_to_stock(doc, line)
		else:
			line["purchase_return"] = _return_to_supplier(doc, line)
	refund_total = sum(r["amount"] for r in refunds)
	_close(doc, reason, refund_total, lines)
	_review(doc, reason, refund_total)
	return {
		"refunds": refund_entries,
		"refund_amount": refund_total,
		"deleted_orders": deleted,
		"flagged_orders": flagged,
		"lines": lines,
	}


def _refund(doc, row: dict) -> str:
	"""A Pay entry back to the customer, pending the admin's confirmation (A1)."""
	from smart_power.sp_finance.centers import station_center
	from smart_power.sp_finance.supplier_payment import _confirm_task

	amount = row["amount"]
	entry = frappe.get_doc(
		{
			"doctype": ENTRY,
			"payment_type": "Pay",
			"party_type": "Customer",
			"party": doc.customer,
			"company": doc.company,
			"posting_date": today(),
			"paid_from": row["refund_from"],
			"paid_amount": amount,
			"received_amount": amount,
			"reference_no": row["payment"],
			"reference_date": today(),
			"mode_of_payment": row.get("mode"),
			"project": doc.project,
			"cost_center": station_center(doc.company),
			"remarks": _("Refund of {0}: station {1} cancelled").format(row["payment"], doc.name),
			"sp_payment_status": PENDING,
			"sp_recorded_by": frappe.session.user,
			"sp_refund_of": row["payment"],
		}
	)
	entry.flags.ignore_permissions = True
	frappe.flags.sp_system_posting = True
	try:
		entry.setup_party_account_field()
		entry.set_missing_values()
		entry.insert()
	finally:
		frappe.flags.sp_system_posting = False
	_confirm_task(entry)
	return entry.name


def _release_reservations(doc) -> None:
	if not doc.sales_order:
		return
	from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
		cancel_stock_reservation_entries,
	)

	if frappe.db.exists(
		"Stock Reservation Entry",
		{"voucher_type": "Sales Order", "voucher_no": doc.sales_order, "docstatus": 1},
	):
		cancel_stock_reservation_entries(voucher_type="Sales Order", voucher_no=doc.sales_order, notify=False)


def _orders(doc, reason: str) -> tuple[list[str], list[str]]:
	"""Draft orders go; a submitted order is the projects manager's to settle with the supplier."""
	from smart_power.sp_core.inbox import create_task
	from smart_power.sp_sales.quote_request import _users_with

	deleted = frappe.get_all(PO, {"sp_station": doc.name, "docstatus": 0}, pluck="name")
	for name in deleted:
		frappe.delete_doc(PO, name, ignore_permissions=True)
	flagged = frappe.get_all(PO, {"sp_station": doc.name, "docstatus": 1}, pluck="name")
	managers = [doc.execution_owner] if doc.execution_owner else _users_with(PM_ROLE)
	for name in flagged:
		create_task(
			"Other",
			PO,
			name,
			managers,
			_("Station {0} was cancelled: settle purchase order {1} with the supplier").format(
				doc.name, name
			),
			description=reason,
		)
	return deleted, flagged


def _main_store(doc) -> str:
	from smart_power.sp_stock.warehouses import MAIN, warehouse_of

	main = warehouse_of(doc.company, MAIN)
	if not main:
		frappe.throw(_("Company {0} has no main store.").format(doc.company))
	return main


def _back_to_stock(doc, line: dict) -> str:
	"""The site's goods back to the main store, at cost (a material transfer keeps the valuation)."""
	main = _main_store(doc)
	entry = frappe.get_doc(
		{
			"doctype": STOCK_ENTRY,
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": doc.company,
			"from_warehouse": line["warehouse"],
			"to_warehouse": main,
			"project": doc.project,
			"sp_station": doc.name,
			"remarks": _("Station {0} cancelled: back to the main store").format(doc.name),
			"items": [
				{
					"item_code": line["item_code"],
					"qty": line["qty"],
					"s_warehouse": line["warehouse"],
					"t_warehouse": main,
					"project": doc.project,
				}
			],
		}
	)
	entry.flags.ignore_permissions = True
	frappe.flags.sp_system_posting = True
	try:
		entry.insert()
		entry.submit()
	finally:
		frappe.flags.sp_system_posting = False
	return entry.name


def _return_to_supplier(doc, line: dict) -> str:
	"""A Purchase Return of the line's quantity, out of the site, against its receipt."""
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_return

	ret = make_purchase_return(line["purchase_receipt"])
	rows = [r for r in ret.items if r.item_code == line["item_code"]]
	ret.set("items", rows[:1])
	row = ret.items[0]
	row.qty = row.received_qty = -flt(line["qty"])
	row.stock_qty = row.qty * flt(row.conversion_factor or 1)
	row.warehouse = line["warehouse"]
	row.project = doc.project
	ret.remarks = _("Station {0} cancelled: returned to the supplier").format(doc.name)
	ret.flags.ignore_permissions = True
	ret.flags.sp_confirming = True  # the admin's own return, not a receiver's delivery (SP-84)
	frappe.flags.sp_system_posting = True
	try:
		ret.insert()
		ret.submit()
	finally:
		frappe.flags.sp_system_posting = False
	return ret.name


def _close(doc, reason: str, refund_total: float, lines: list[dict]) -> None:
	doc.reload()
	doc.cancelled_on = today()
	doc.refund_amount = refund_total
	doc.cancel_reason = reason
	doc.set(
		"cancel_lines",
		[
			{
				key: line.get(key)
				for key in (
					"item_code",
					"item_name",
					"qty",
					"warehouse",
					"fate",
					"purchase_receipt",
					"stock_entry",
					"purchase_return",
				)
			}
			for line in lines
		],
	)
	doc.flags.ignore_permissions = True
	doc.save()
	# the workflow has no Cancel transition: a station is cancelled only here, with its refunds
	doc.db_set("status", CANCELLED)
	doc.add_comment("Info", _("Cancelled: {0}").format(reason))
	if doc.sales_order and frappe.db.get_value("Sales Order", doc.sales_order, "docstatus") == 1:
		so = frappe.get_doc("Sales Order", doc.sales_order)
		so.flags.ignore_permissions = True
		so.update_status("Closed")
	if doc.case:
		values = {"status": LOST, "lost_on": today(), "lost_note": reason}
		lost = frappe.db.get_value("SP List Value", {"list_name": LOST_REASON[0], "code": LOST_REASON[1]})
		if lost:
			values["lost_reason"] = lost
		frappe.db.set_value(CASE, doc.case, values)


def _review(doc, reason: str, refund_total: float) -> None:
	from smart_power.sp_core.review_centre import raise_item

	raise_item(
		"Station Cancellation",
		doc,
		_("Station {0} ({1}) cancelled: {2}").format(doc.name, doc.customer_name or doc.customer, reason),
		amount=refund_total,
		highlight=True,
	)
