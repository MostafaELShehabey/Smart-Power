"""Receipt confirmation (SP-85, P4): the technical office checks what the receiver recorded.

A receipt waits as a draft Purchase Receipt, Pending confirmation (SP-84). From here it is:

    confirm_receipt(receipt)            everything arrived as recorded: stock and the payable post
    mark_discrepancy(receipt, notes)    the good quantity posts, the damaged quantity stays open
                                        on the order, and the admin and purchasing are told
    reject_receipt(receipt, reason)     nothing posts; the receiver gets a task with the reason

Posting submits the receipt on the date the goods arrived, then bills it with a submitted Purchase
Invoice on the supplier's payment terms. Lines of a station carry its Project and the Projects
cost center. Site deliveries go into the site warehouse and reach the station's cost when they
are consumed on the daily log; a shared order's value goes to its stations at once (SP-83). A line reserved for a sales order stays reserved once received.
"""

import frappe
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
	create_stock_reservation_entries_for_so_items,
)
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.utils import cstr, flt, get_fullname

from smart_power.notify import send
from smart_power.sp_core.inbox import close_tasks, create_task
from smart_power.sp_finance.centers import PROJECTS, center
from smart_power.sp_stock.goods_receipt import (
	CONFIRMED,
	CONFIRMER,
	DISCREPANCY,
	PENDING,
	PO_ITEM,
	RECEIPT,
	RECEIPT_ITEM,
	REJECT_TASK,
	REJECTED,
	TASK_TYPE,
	_is_serial,
	_sees_all,
)
from smart_power.sp_stock.iron_weight import settle_weighed_lines
from smart_power.sp_stock.shared_purchase import allocate

OK, DAMAGED = "OK", "Damaged"
INVOICE = "Purchase Invoice"
EVENT_REJECTED, EVENT_DISCREPANCY = "goods_receipt_rejected", "goods_receipt_discrepancy"
TOLD_OF_DISCREPANCY = ("SP Admin", "SP Purchase Officer")


def _check_confirmer() -> None:
	user = frappe.session.user
	if not (_sees_all(user) or CONFIRMER in frappe.get_roles(user)):
		frappe.throw(_("Only the technical office confirms receipts."), frappe.PermissionError)


def _pending(receipt: str):
	"""The receipt, locked, so two people cannot act on it at once."""
	_check_confirmer()
	status = frappe.db.get_value(RECEIPT, receipt, "sp_receipt_status", for_update=True)
	if status != PENDING:
		frappe.throw(_("Receipt {0} is not waiting for confirmation.").format(receipt))
	return frappe.get_doc(RECEIPT, receipt)


def _check_serials(rows) -> None:
	for row in rows:
		if _is_serial(row.item_code) and not (row.serial_no and row.sp_serial_photo):
			frappe.throw(
				_("Row {0}: {1} needs its serial and nameplate photo.").format(row.idx, row.item_code)
			)


def _set_center(doc) -> None:
	"""What belongs to a station posts to its Project and the Projects cost center."""
	projects = center(PROJECTS, doc.company)
	for row in doc.items:
		if row.project:
			row.cost_center = projects
	stations = {row.project for row in doc.items if row.project}
	if len(stations) == 1:
		doc.project = stations.pop()
		doc.cost_center = projects


def _keep_reservation(doc) -> None:
	"""A line reserved for a sales order stays reserved on the quantity received."""
	if frappe.db.get_single_value("Stock Settings", "auto_reserve_stock_for_sales_order_on_purchase"):
		return  # ERPNext reserved it on submit
	if not frappe.db.get_single_value("Stock Settings", "enable_stock_reservation"):
		return
	orders: dict[str, list[dict]] = {}
	for row in doc.items:
		if row.sales_order_item and frappe.db.get_value(
			"Sales Order Item", row.sales_order_item, "reserve_stock"
		):
			orders.setdefault(row.sales_order, []).append(
				{
					"sales_order_item": row.sales_order_item,
					"item_code": row.item_code,
					"warehouse": row.warehouse,
					"qty_to_reserve": row.stock_qty,
					"from_voucher_no": doc.name,
					"from_voucher_detail_no": row.name,
					"serial_and_batch_bundle": row.serial_and_batch_bundle,
				}
			)
	for order, items in orders.items():
		sales_order = frappe.get_doc("Sales Order", order)
		if sales_order.docstatus == DocStatus.submitted():  # a draft order reserves nothing yet
			create_stock_reservation_entries_for_so_items(
				sales_order, items, "Purchase Receipt", notify=False
			)


def _bill_no(doc) -> str:
	"""The order and its batch; a second delivery of one batch takes the next number."""
	lines = [row.purchase_order_item for row in doc.items]
	batches = sorted(set(frappe.get_all(PO_ITEM, {"name": ("in", lines)}, pluck="sp_batch_no")))
	base = f"{doc.sp_purchase_order}-{'+'.join(str(b) for b in batches)}"
	taken = frappe.db.count(INVOICE, {"supplier": doc.supplier, "bill_no": ("like", f"{base}%")})
	return f"{base}-{taken + 1}" if taken else base


def _bill(doc) -> str:
	"""The supplier's payable for what was received."""
	invoice = make_purchase_invoice(doc.name)
	invoice.update(
		{
			"bill_no": _bill_no(doc),
			"bill_date": doc.posting_date,
			"posting_date": doc.posting_date,
			"set_posting_time": 1,
			"project": doc.project,
			"cost_center": doc.cost_center,
		}
	)
	invoice.flags.ignore_permissions = True
	invoice.insert()
	invoice.submit()
	return invoice.name


def _post(doc, status: str, notes: str | None = None) -> str:
	"""Submit the receipt and bill it. The confirmer may not read accounts or prices, and ERPNext
	checks both against the session user, so only this posting runs as the administrator."""
	user = frappe.session.user
	doc.update(
		{
			"sp_receipt_status": status,
			"sp_confirmed_by": user,
			"sp_discrepancy_notes": notes,
			"set_posting_time": 1,  # the day the goods arrived
		}
	)
	doc.flags.sp_confirming = True
	doc.flags.ignore_permissions = True
	_set_center(doc)
	frappe.set_user("Administrator")  # nosemgrep
	try:
		settle_weighed_lines(doc)  # iron: the scale weight is final (SP-178)
		doc.submit()
		_keep_reservation(doc)
		invoice = _bill(doc)
		allocate(doc, invoice)  # a shared order's value goes to its stations (SP-83)
	finally:
		frappe.set_user(user)  # nosemgrep
	frappe.db.set_value(INVOICE, invoice, {"owner": user, "modified_by": user}, update_modified=False)
	doc.db_set("modified_by", user, update_modified=False)
	close_tasks(RECEIPT, doc.name, TASK_TYPE)
	return invoice


@frappe.whitelist(methods=["POST"])
def confirm_receipt(receipt: str) -> dict:
	"""Everything arrived as recorded."""
	doc = _pending(receipt)
	if any(row.sp_condition != OK for row in doc.items):
		frappe.throw(_("Some lines are damaged or short. Mark a discrepancy instead."))
	_check_serials(doc.items)
	return {"name": doc.name, "status": CONFIRMED, "purchase_invoice": _post(doc, CONFIRMED)}


@frappe.whitelist(methods=["POST"])
def mark_discrepancy(receipt: str, notes: str | None = None) -> dict:
	"""The good quantity posts. What came damaged leaves the receipt, so it stays open on the order."""
	notes = cstr(notes).strip()
	if not notes:
		frappe.throw(_("Describe the discrepancy."))
	doc = _pending(receipt)
	good = [row for row in doc.items if row.sp_condition != DAMAGED]
	if not good:
		frappe.throw(_("Nothing arrived in good condition. Reject the receipt instead."))
	_check_serials(good)
	damaged = [
		f"{flt(r.qty):g} x {r.item_name or r.item_code}: {_(DAMAGED)}"
		for r in doc.items
		if r.sp_condition == DAMAGED
	]
	doc.set("items", good)
	for idx, row in enumerate(doc.items, start=1):
		row.idx = idx
	invoice = _post(doc, DISCREPANCY, "\n".join([notes, *damaged]))
	subject = _("Discrepancy on goods receipt {0}: {1}").format(doc.name, notes)
	users = {u for role in TOLD_OF_DISCREPANCY for u in _users_with(role)}
	send(EVENT_DISCREPANCY, sorted(users), RECEIPT, doc.name, subject)
	return {"name": doc.name, "status": DISCREPANCY, "purchase_invoice": invoice}


@frappe.whitelist(methods=["POST"])
def reject_receipt(receipt: str, reason: str | None = None) -> dict:
	"""Nothing posts. The receipt stays a draft, and the receiver can record the delivery again."""
	reason = cstr(reason).strip()
	if not reason:
		frappe.throw(_("Give the reason for rejecting."))
	doc = _pending(receipt)
	doc.db_set(
		{"sp_receipt_status": REJECTED, "sp_reject_reason": reason, "sp_confirmed_by": frappe.session.user}
	)
	close_tasks(RECEIPT, doc.name, TASK_TYPE)
	subject = _("Goods receipt {0} was rejected: {1}").format(doc.name, reason)
	create_task(REJECT_TASK, RECEIPT, doc.name, doc.sp_received_by, subject, description=reason)
	send(EVENT_REJECTED, [doc.sp_received_by], RECEIPT, doc.name, subject)
	return {"name": doc.name, "status": REJECTED}


def _users_with(role: str) -> list[str]:
	users = frappe.get_all("Has Role", {"role": role, "parenttype": "User"}, pluck="parent")
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")


@frappe.whitelist()
def pending_receipts() -> list[dict]:
	"""The receipts to check, each line against its order. Never reads a price."""
	_check_confirmer()
	receipts = frappe.get_all(
		RECEIPT,
		{"docstatus": 0, "sp_receipt_status": PENDING},
		[
			"name",
			"supplier_name",
			"sp_purchase_order as purchase_order",
			"sp_received_by as received_by",
			"sp_exit_permit_image as exit_permit",
			"sp_signature as signature",
			"set_warehouse as warehouse",
			"posting_date",
		],
		order_by="creation asc",
	)
	if not receipts:
		return []
	lines = frappe.get_all(
		RECEIPT_ITEM,
		{"parent": ("in", [r.name for r in receipts])},
		[
			"parent",
			"item_code",
			"item_name",
			"uom",
			"received_qty",
			"sp_condition as condition",
			"sp_line_note as note",
			"serial_no",
			"sp_serial_photo as serial_photo",
			"purchase_order_item",
		],
		order_by="idx asc",
	)
	ordered = {
		r.name: r
		for r in frappe.get_all(
			PO_ITEM, {"name": ("in", [l.purchase_order_item for l in lines])}, ["name", "qty", "received_qty"]
		)
	}
	by_receipt: dict[str, list] = {}
	for line in lines:
		order_line = ordered.get(line.purchase_order_item) or frappe._dict()
		line.update({"ordered": flt(order_line.qty), "already_received": flt(order_line.received_qty)})
		by_receipt.setdefault(line.pop("parent"), []).append(line)
	for receipt in receipts:
		receipt.update(
			{
				"lines": by_receipt.get(receipt.name, []),
				"received_by_name": get_fullname(receipt.received_by),
				"posting_date": str(receipt.posting_date),
			}
		)
	return receipts
