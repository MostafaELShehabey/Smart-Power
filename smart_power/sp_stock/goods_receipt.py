"""Receive goods (SP-84, P3): what arrived against a purchase order, before anyone confirms it.

A receiver sees the deliveries expected at their own destinations, records the quantity and
condition of each line, photographs the supplier's exit permit and signs. The receipt then waits
for the technical office (SP-85): nothing touches stock or the ledger until it is confirmed.

    my_warehouses(user)      a store's responsible user, else the holders of its receiving role;
                             a site's receiver on the station, else the site receivers
    expected_deliveries()    open purchase order lines at those warehouses, without any price
    record_receipt(...)      the receipt, Pending confirmation, with a task for the confirmers

Quantities on receipts still waiting count as received, so one delivery is not recorded twice.
Receipts against a transfer order come with the transfer orders (SP-88).
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, today

from smart_power.notify import send
from smart_power.sp_core.inbox import create_task
from smart_power.sp_stock.purchase_orders import OPEN_STATUSES
from smart_power.sp_stock.warehouses import MAIN, SHOWROOM, SITE

RECEIPT, LINE, PO, PO_ITEM = "SP Goods Receipt", "SP GR Line", "Purchase Order", "Purchase Order Item"
RECORDED, PENDING, CONFIRMED, REJECTED, DISCREPANCY = (
	"Recorded",
	"Pending confirmation",
	"Confirmed",
	"Rejected",
	"Discrepancy",
)
WAITING = (RECORDED, PENDING, DISCREPANCY)
CONDITIONS = ("OK", "Damaged", "Short")
TASK_TYPE, EVENT = "Receipt to Confirm", "receipt_to_confirm"
CONFIRMER = "SP Receipt Confirmer"
ADMIN_ROLES = ("SP Admin", "System Manager")
STORE_ROLES = {MAIN: "SP Main Store Keeper", SHOWROOM: "SP Showroom Store Keeper"}
SITE_ROLE = "SP Site Receiver"
QTY_DIGITS = 3  # sp-allow-number: quantities to a thousandth, so rounding never blocks a receipt


def _sees_all(user: str) -> bool:
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def my_warehouses(user: str | None = None) -> list[str]:
	"""The warehouses this user receives goods at."""
	user = user or frappe.session.user
	rows = frappe.get_all(
		"Warehouse",
		{"is_group": 0, "disabled": 0},
		["name", "warehouse_type", "sp_responsible_user", "sp_project"],
	)
	if _sees_all(user):
		return [r.name for r in rows]
	roles = set(frappe.get_roles(user))
	receivers = dict(
		frappe.get_all("SP Station", {"project": ("is", "set")}, ["project", "site_receiver"], as_list=True)
	)
	mine = []
	for row in rows:
		if row.sp_responsible_user:
			allowed = row.sp_responsible_user == user
		elif row.warehouse_type == SITE:
			receiver = receivers.get(row.sp_project)
			allowed = receiver == user if receiver else SITE_ROLE in roles
		else:
			allowed = STORE_ROLES.get(row.warehouse_type) in roles
		if allowed:
			mine.append(row.name)
	return mine


def waiting_qty(po_items: list[str], exclude: str | None = None) -> dict[str, float]:
	"""What receipts still waiting for confirmation hold, per purchase order line."""
	if not po_items:
		return {}
	receipt, line = frappe.qb.DocType(RECEIPT), frappe.qb.DocType(LINE)
	query = (
		frappe.qb.from_(line)
		.join(receipt)
		.on(line.parent == receipt.name)
		.select(line.purchase_order_item, line.received_qty)
		.where(line.purchase_order_item.isin(po_items))
		.where(receipt.status.isin(WAITING))
	)
	if exclude:
		query = query.where(receipt.name != exclude)
	totals: dict[str, float] = {}
	for row in query.run(as_dict=True):
		totals[row.purchase_order_item] = totals.get(row.purchase_order_item, 0) + flt(row.received_qty)
	return totals


def _open_lines(warehouses: list[str], purchase_order: str | None = None) -> list:
	"""The open lines at these warehouses. Never reads a price."""
	if not warehouses:
		return []
	filters = {"warehouse": ("in", warehouses), "docstatus": 1, "parenttype": PO}
	if purchase_order:
		filters["parent"] = purchase_order
	rows = frappe.get_all(
		PO_ITEM,
		filters,
		[
			"name",
			"parent",
			"item_code",
			"item_name",
			"uom",
			"qty",
			"received_qty",
			"warehouse",
			"schedule_date",
			"sp_batch_no",
			"sp_station",
		],
		order_by="schedule_date asc, idx asc",
	)
	orders = {r.parent for r in rows}
	open_orders = set(
		frappe.get_all(PO, {"name": ("in", list(orders)), "sp_status": ("in", OPEN_STATUSES)}, pluck="name")
		if orders
		else []
	)
	return [r for r in rows if r.parent in open_orders]


@frappe.whitelist()
def expected_deliveries() -> list[dict]:
	"""What is expected at my destinations, one card per order and warehouse."""
	rows = _open_lines(my_warehouses())
	waiting = waiting_qty([r.name for r in rows])
	cards: dict[tuple, dict] = {}
	for row in rows:
		pending = waiting.get(row.name, 0)
		remaining = flt(flt(row.qty) - flt(row.received_qty) - pending, QTY_DIGITS)
		if remaining <= 0:
			continue
		card = cards.setdefault(
			(row.parent, row.warehouse),
			{
				"purchase_order": row.parent,
				"warehouse": row.warehouse,
				"supplier": frappe.db.get_value(PO, row.parent, "supplier_name"),
				"station": row.sp_station,
				"due": str(row.schedule_date) if row.schedule_date else None,
				"lines": [],
			},
		)
		card["lines"].append(
			{
				"purchase_order_item": row.name,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"uom": row.uom,
				"batch": row.sp_batch_no,
				"due": str(row.schedule_date) if row.schedule_date else None,
				"ordered": flt(row.qty),
				"received": flt(row.received_qty) + pending,
				"remaining": remaining,
			}
		)
	return list(cards.values())


@frappe.whitelist(methods=["POST"])
def record_receipt(
	purchase_order: str,
	warehouse: str,
	lines: list | str,
	exit_permit_photo: str | None = None,
	signature: str | None = None,
) -> dict:
	"""Record what arrived. lines: [{purchase_order_item, received_qty, condition, note}]."""
	doc = frappe.get_doc(
		{
			"doctype": RECEIPT,
			"purchase_order": purchase_order,
			"destination_warehouse": warehouse,
			"exit_permit_photo": exit_permit_photo,
			"signature": signature,
			"lines": frappe.parse_json(lines) if isinstance(lines, str) else lines,
		}
	).insert()
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def my_receipts() -> list[dict]:
	"""My latest receipts, with the confirmer's reason on a rejected one."""
	return frappe.get_all(
		RECEIPT,
		{"received_by": frappe.session.user},
		["name", "purchase_order", "supplier_name", "status", "reject_reason", "work_date"],
		order_by="creation desc",
		limit=20,  # sp-allow-number: a screenful
	)


def _check_lines(doc) -> None:
	rows = {r.name: r for r in _open_lines([doc.destination_warehouse], doc.purchase_order)}
	waiting = waiting_qty(list(rows), exclude=doc.name)
	received: dict[str, float] = {}
	for line in doc.lines:
		row = rows.get(line.purchase_order_item)
		if not row:
			frappe.throw(_("Row {0} is not an open line of this order at this destination.").format(line.idx))
		if flt(line.received_qty) <= 0:
			frappe.throw(_("Row {0}: enter the quantity received.").format(line.idx))
		if line.condition not in CONDITIONS:
			frappe.throw(_("Row {0}: choose the condition.").format(line.idx))
		before = flt(row.received_qty) + waiting.get(row.name, 0)
		line.update(
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"uom": row.uom,
				"ordered_qty": flt(row.qty),
				"prev_received": before,
			}
		)
		received[row.name] = received.get(row.name, 0) + flt(line.received_qty)
		if flt(before + received[row.name], QTY_DIGITS) > flt(row.qty, QTY_DIGITS):
			frappe.throw(
				_("{0}: only {1} of {2} are still expected.").format(
					row.item_name or row.item_code, flt(flt(row.qty) - before, QTY_DIGITS), flt(row.qty)
				),
				title=_("More than was ordered"),
			)


def validate(doc) -> None:
	if not doc.is_new():
		if not doc.flags.get("sp_confirming"):
			frappe.throw(_("A recorded receipt cannot be changed."))
		return
	user = frappe.session.user
	if doc.destination_warehouse not in my_warehouses(user):
		frappe.throw(
			_("You do not receive goods at {0}.").format(doc.destination_warehouse), frappe.PermissionError
		)
	if not doc.exit_permit_photo:
		frappe.throw(_("Attach the photo of the supplier's exit permit."), frappe.MandatoryError)
	if not doc.signature:
		frappe.throw(_("Sign the receipt."), frappe.MandatoryError)
	if not doc.lines:
		frappe.throw(_("Enter what was received."))
	_check_lines(doc)
	order = frappe.db.get_value(PO, doc.purchase_order, ["supplier_name", "sp_station"], as_dict=True)
	doc.update(
		{
			"source_type": "PO",
			"status": RECORDED,
			"supplier_name": order.supplier_name,
			"station": order.sp_station,
			"received_by": user,
			"entry_time": now_datetime(),
			"work_date": doc.work_date or today(),
		}
	)


def _confirmers() -> list[str]:
	users = frappe.get_all("Has Role", {"role": CONFIRMER, "parenttype": "User"}, pluck="parent")
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")


def _attach_permit(doc) -> None:
	"""The receiver's private photo joins the receipt, so whoever may read the receipt can open it."""
	name = frappe.db.get_value(
		"File",
		{"file_url": doc.exit_permit_photo, "owner": doc.received_by, "attached_to_name": ("is", "not set")},
	)
	if name:
		frappe.db.set_value(
			"File",
			name,
			{
				"attached_to_doctype": RECEIPT,
				"attached_to_name": doc.name,
				"attached_to_field": "exit_permit_photo",
			},
		)


def after_insert(doc) -> None:
	"""The receipt waits for the technical office; stock and the ledger stay as they are."""
	doc.db_set("status", PENDING)
	_attach_permit(doc)
	users = _confirmers()
	subject = _("Goods receipt {0} to confirm: {1}").format(doc.name, doc.supplier_name or doc.purchase_order)
	create_task(TASK_TYPE, RECEIPT, doc.name, users, subject)
	send(EVENT, users, RECEIPT, doc.name, subject)


def query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _sees_all(user) or CONFIRMER in frappe.get_roles(user):
		return ""
	return f"`tabSP Goods Receipt`.received_by = {frappe.db.escape(user)}"


def has_permission(doc, ptype=None, user=None) -> bool:
	user = user or frappe.session.user
	if doc.is_new() or _sees_all(user) or CONFIRMER in frappe.get_roles(user):
		return True
	return doc.received_by == user
