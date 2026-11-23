"""Receive goods (SP-84, P3): what arrived against a purchase order, before anyone confirms it.

A receiver sees the deliveries expected at their own destinations, records the quantity, condition
and serial of each line, photographs the supplier's exit permit and signs. That saves a draft
Purchase Receipt, Pending confirmation. It is submitted only on confirmation (SP-85), so nothing
touches stock or the ledger before then, and the receiver never sees a price.

    my_warehouses(user)      a store's responsible user, else the holders of its receiving role;
                             a site's receiver on the station, else the site receivers
    expected_deliveries()    open purchase order lines at those warehouses, without any price
    record_receipt(...)      the draft receipt, with a task for the confirmers

Quantities on receipts still waiting count as received, so one delivery is not recorded twice.
A serial-tracked item is recorded one unit per line, with its serial and nameplate photo. Receipts
against a transfer order are confirmed on the Stock Entry (SP-88).
"""

import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from frappe import _
from frappe.utils import cstr, flt

from smart_power.notify import send
from smart_power.sp_core.inbox import close_tasks, create_task
from smart_power.sp_stock.iron_weight import is_weighed
from smart_power.sp_stock.purchase_orders import OPEN_STATUSES
from smart_power.sp_stock.warehouses import MAIN, SHOWROOM, SITE

RECEIPT, RECEIPT_ITEM, PO, PO_ITEM = (
	"Purchase Receipt",
	"Purchase Receipt Item",
	"Purchase Order",
	"Purchase Order Item",
)
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
REJECT_TASK = "Receipt Rejected"
CONFIRMER = "SP Receipt Confirmer"
ADMIN_ROLES = ("SP Admin", "System Manager")
STORE_ROLES = {MAIN: "SP Main Store Keeper", SHOWROOM: "SP Showroom Store Keeper"}
SITE_ROLE = "SP Site Receiver"
QTY_DIGITS = 3  # sp-allow-number: quantities to a thousandth, so rounding never blocks a receipt
RECENT = 20  # sp-allow-number: a screenful of my latest receipts


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


def waiting_qty(po_items: list[str]) -> dict[str, float]:
	"""What draft receipts still waiting for confirmation hold, per purchase order line."""
	if not po_items:
		return {}
	receipt, line = frappe.qb.DocType(RECEIPT), frappe.qb.DocType(RECEIPT_ITEM)
	rows = (
		frappe.qb.from_(line)
		.join(receipt)
		.on(line.parent == receipt.name)
		.select(line.purchase_order_item, line.received_qty)
		.where(line.purchase_order_item.isin(po_items))
		.where(receipt.docstatus == 0)
		.where(receipt.sp_receipt_status.isin(WAITING))
	).run(as_dict=True)
	totals: dict[str, float] = {}
	for row in rows:
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


def _is_serial(item_code: str) -> bool:
	return bool(frappe.get_cached_value("Item", item_code, "has_serial_no"))


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
				"serial": _is_serial(row.item_code),
				"weighed": is_weighed(row.item_code),
			}
		)
	return list(cards.values())


def _check_serial(line: dict, row, seen: set, position: int) -> None:
	serial = cstr(line.get("serial_no")).strip()
	if flt(line.get("received_qty")) != 1:
		frappe.throw(_("Row {0}: record {1} one unit per row.").format(position, row.item_code))
	if not serial:
		frappe.throw(_("Row {0}: enter the serial number of {1}.").format(position, row.item_code))
	if not line.get("serial_photo"):
		frappe.throw(_("Row {0}: attach the nameplate photo of {1}.").format(position, row.item_code))
	taken = serial in seen or frappe.db.exists("Serial No", serial)
	receipt, item = frappe.qb.DocType(RECEIPT), frappe.qb.DocType(RECEIPT_ITEM)
	waiting = (
		frappe.qb.from_(item)
		.join(receipt)
		.on(item.parent == receipt.name)
		.select(item.name)
		.where(item.serial_no == serial)
		.where(receipt.docstatus == 0)
		.where(receipt.sp_receipt_status.isin(WAITING))
		.limit(1)
	).run()
	if taken or waiting:
		frappe.throw(_("Serial number {0} is already recorded.").format(frappe.bold(serial)))
	seen.add(serial)


def _check_lines(purchase_order: str, warehouse: str, lines: list[dict]) -> None:
	rows = {r.name: r for r in _open_lines([warehouse], purchase_order)}
	waiting = waiting_qty(list(rows))
	received: dict[str, float] = {}
	serials: set[str] = set()
	for position, line in enumerate(lines, start=1):
		row = rows.get(line.get("purchase_order_item"))
		if not row:
			frappe.throw(_("Row {0} is not an open line of this order at this destination.").format(position))
		if flt(line.get("received_qty")) <= 0:
			frappe.throw(_("Row {0}: enter the quantity received.").format(position))
		if line.get("condition") not in CONDITIONS:
			frappe.throw(_("Row {0}: choose the condition.").format(position))
		if _is_serial(row.item_code):
			_check_serial(line, row, serials, position)
		before = flt(row.received_qty) + waiting.get(row.name, 0)
		received[row.name] = received.get(row.name, 0) + flt(line.get("received_qty"))
		if is_weighed(row.item_code):
			continue  # iron: the scale weight is final, above or below the order (SP-178)
		if flt(before + received[row.name], QTY_DIGITS) > flt(row.qty, QTY_DIGITS):
			frappe.throw(
				_("{0}: only {1} of {2} are still expected.").format(
					row.item_name or row.item_code, flt(flt(row.qty) - before, QTY_DIGITS), flt(row.qty)
				),
				title=_("More than was ordered"),
			)


def _draft_receipt(purchase_order: str, warehouse: str, lines: list[dict]):
	"""ERPNext's own receipt from the order, holding only what arrived."""
	doc = make_purchase_receipt(purchase_order)
	mapped = {row.purchase_order_item: row.as_dict() for row in doc.items}
	doc.set("items", [])
	for line in lines:
		row = {k: v for k, v in mapped[line["purchase_order_item"]].items() if k not in ("name", "idx")}
		serial = cstr(line.get("serial_no")).strip()
		qty = flt(line["received_qty"])
		row.update(
			{
				"qty": qty,
				"received_qty": qty,
				"rejected_qty": 0,
				"warehouse": warehouse,
				"sp_condition": line["condition"],
				"sp_line_note": line.get("note"),
				"serial_no": serial or None,
				"use_serial_batch_fields": 1 if serial else 0,
				"sp_serial_photo": line.get("serial_photo"),
			}
		)
		doc.append("items", row)
	doc.set_warehouse = warehouse
	return doc


EVIDENCE_FIELDS = ("sp_exit_permit_image", "sp_serial_photo")


def _attach(doc, file_url: str | None, field: str) -> None:
	"""The receiver's private photo joins the receipt, so whoever may read the receipt can open it."""
	name = file_url and frappe.db.get_value(
		"File", {"file_url": file_url, "owner": frappe.session.user, "attached_to_name": ("is", "not set")}
	)
	if name:
		frappe.db.set_value(
			"File",
			name,
			{"attached_to_doctype": RECEIPT, "attached_to_name": doc.name, "attached_to_field": field},
		)


def _check_own_photo(file_url: str | None) -> None:
	"""A receipt only takes photos its receiver uploaded: saving it attaches them to the receipt."""
	if file_url and not frappe.db.exists("File", {"file_url": file_url, "owner": frappe.session.user}):
		frappe.throw(_("Attach a photo you uploaded yourself."), frappe.PermissionError)


def _confirmers() -> list[str]:
	users = frappe.get_all("Has Role", {"role": CONFIRMER, "parenttype": "User"}, pluck="parent")
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")


@frappe.whitelist(methods=["POST"])
def record_receipt(
	purchase_order: str,
	warehouse: str,
	lines: list | str,
	exit_permit_photo: str | None = None,
	signature: str | None = None,
) -> dict:
	"""Record what arrived.
	lines: [{purchase_order_item, received_qty, condition, note, serial_no, serial_photo}]."""
	user = frappe.session.user
	lines = frappe.parse_json(lines) if isinstance(lines, str) else lines
	if warehouse not in my_warehouses(user):
		frappe.throw(_("You do not receive goods at {0}.").format(warehouse), frappe.PermissionError)
	if not exit_permit_photo:
		frappe.throw(_("Attach the photo of the supplier's exit permit."), frappe.MandatoryError)
	if not signature:
		frappe.throw(_("Sign the receipt."), frappe.MandatoryError)
	if not lines:
		frappe.throw(_("Enter what was received."))
	_check_lines(purchase_order, warehouse, lines)
	for file_url in (exit_permit_photo, *(line.get("serial_photo") for line in lines)):
		_check_own_photo(file_url)
	doc = _draft_receipt(purchase_order, warehouse, lines)
	doc.update(
		{
			"sp_receipt_status": RECORDED,
			"sp_purchase_order": purchase_order,
			"sp_received_by": user,
			"sp_exit_permit_image": exit_permit_photo,
			"sp_signature": signature,
		}
	)
	# the prices and accounts come from the order: a receiver who may not read them must not blank
	# them or be stopped by them. Everything the receiver typed is checked above. ERPNext checks the
	# supplier's account against the session user whatever the flags, so only this insert is elevated.
	frappe.set_user("Administrator")  # nosemgrep
	try:
		doc.insert(ignore_permissions=True)
	finally:
		frappe.set_user(user)  # nosemgrep
	doc.db_set({"sp_receipt_status": PENDING, "owner": user, "modified_by": user}, update_modified=False)
	_attach(doc, exit_permit_photo, "sp_exit_permit_image")
	for line in lines:
		_attach(doc, line.get("serial_photo"), "sp_serial_photo")
	rejected = {"sp_purchase_order": purchase_order, "sp_received_by": user, "sp_receipt_status": REJECTED}
	for name in frappe.get_all(RECEIPT, rejected, pluck="name"):
		close_tasks(RECEIPT, name, REJECT_TASK)  # recorded again
	users = _confirmers()
	subject = _("Goods receipt {0} to confirm: {1}").format(doc.name, doc.supplier_name or purchase_order)
	create_task(TASK_TYPE, RECEIPT, doc.name, users, subject)
	send(EVENT, users, RECEIPT, doc.name, subject)
	return {"name": doc.name, "status": PENDING}


@frappe.whitelist()
def my_receipts() -> list[dict]:
	"""My latest receipts, with the confirmer's reason on a rejected one."""
	return frappe.get_all(
		RECEIPT,
		{"sp_received_by": frappe.session.user},
		[
			"name",
			"sp_purchase_order as purchase_order",
			"supplier_name",
			"sp_receipt_status as status",
			"sp_reject_reason as reject_reason",
			"posting_date as work_date",
		],
		order_by="creation desc",
		limit=RECENT,
	)


def validate(doc, method=None) -> None:
	"""Purchase Receipt validate: a recorded receipt is the receiver's word, kept as it was."""
	if doc.get("sp_receipt_status") and not doc.is_new() and not doc.flags.get("sp_confirming"):
		frappe.throw(_("A recorded receipt cannot be changed."))


def keep_evidence(doc, method=None) -> None:
	"""File on_trash: the exit permit and nameplate photos stay as long as their receipt does."""
	if (
		doc.attached_to_doctype == RECEIPT
		and doc.attached_to_field in EVIDENCE_FIELDS
		and frappe.db.get_value(RECEIPT, doc.attached_to_name, "sp_receipt_status")
	):
		frappe.throw(_("The photos of a recorded receipt cannot be removed."), frappe.PermissionError)


def before_submit(doc, method=None) -> None:
	"""Stock and the ledger move only when the technical office confirms a delivery."""
	if doc.flags.get("sp_confirming"):
		return
	if doc.get("sp_receipt_status"):
		frappe.throw(_("This receipt is confirmed by the technical office."), frappe.PermissionError)
	user = frappe.session.user
	if _sees_all(user) or CONFIRMER in frappe.get_roles(user):
		return
	orders = {r.purchase_order for r in doc.items if r.get("purchase_order")}
	for order in orders:
		if not frappe.db.get_value(PO, order, "sp_is_consignment_conversion"):
			frappe.throw(_("Record deliveries from Receive Goods."), frappe.PermissionError)
