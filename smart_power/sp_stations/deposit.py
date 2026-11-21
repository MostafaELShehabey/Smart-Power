"""The confirmed deposit turns an approved quote into a station (SP-175; decisions 55, 58, 67;
tech plan section 9).

The trigger is a customer Payment Entry marked Deposit, on a case, when it is confirmed: its
submit is the confirmation (SP-114/SP-115 put the confirm workflow in front of it). A rejected
deposit is never submitted, so nothing below happens.

While the deposit is confirmed (before_submit), so it can be allocated as an advance:
1. the contract (Sales Order) is made from the approved version if there is none (SP-74), and
   submitted; the Project and the Station are made with it and linked one to one;
2. the estimate is frozen (a snapshot of the cost lines and totals, with its time);
3. the deposit carries the station's project and is allocated to the order as an advance.

Then in the background (run_deposit), each step checking what exists first, so a retry changes
nothing:
4. draft Purchase Orders, one per default supplier, for the lines the main store cannot cover
   (source Deposit, assigned to the projects manager);
5. stock reserved against the order for the lines in stock;
6. a technical review task for the admin (it never blocks);
7. the case Won, the approved version Approved, the case's other versions Superseded;
8. the projects manager and the admin are told.
"""

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.utils import add_days, flt, today

SO, PO, CASE, STATION, QUOTE, TASK = (
	"Sales Order",
	"Purchase Order",
	"SP Case",
	"SP Station",
	"Quotation",
	"SP Task",
)
REVIEW_TASK, TASK_OPEN = "Technical Review", "Open"
DEPOSIT_SOURCE = "Deposit"
ADMIN_ROLE = "SP Admin"


def is_deposit(pe) -> bool:
	return bool(
		pe.get("sp_is_deposit")
		and pe.get("sp_case")
		and pe.payment_type == "Receive"
		and pe.party_type == "Customer"
	)


def before_submit(pe, method=None) -> None:
	"""Payment Entry before_submit: the contract and station exist, the deposit is their advance."""
	from smart_power.sp_stations.contract import ensure_contract

	if not is_deposit(pe):
		return
	result = ensure_contract(pe.sp_case, at_deposit=True)
	so = frappe.get_doc(SO, result["sales_order"])
	if so.docstatus.is_draft():
		so.flags.ignore_permissions = True
		so.flags.sp_from_deposit = True  # signed by the deposit; the days can follow (SP-75)
		so.submit()
	pe.project = pe.project or frappe.db.get_value(STATION, result["station"], "project")
	if not any(r.reference_doctype == SO and r.reference_name == so.name for r in pe.references):
		pe.append(
			"references",
			{
				"reference_doctype": SO,
				"reference_name": so.name,
				"total_amount": flt(so.rounded_total or so.grand_total),
				"outstanding_amount": flt(so.rounded_total or so.grand_total) - flt(so.advance_paid),
				"allocated_amount": min(
					flt(pe.paid_amount), flt(so.rounded_total or so.grand_total) - flt(so.advance_paid)
				),
			},
		)
		pe.set_amounts()


def on_submit(pe, method=None) -> None:
	"""Payment Entry on_submit: the rest of the automation runs in the background."""
	if not is_deposit(pe):
		return
	frappe.enqueue(
		"smart_power.sp_stations.deposit.run_deposit",
		queue="short",
		payment_entry=pe.name,
		enqueue_after_commit=True,
		now=frappe.flags.in_test,
	)


def run_deposit(payment_entry: str) -> dict:
	"""Steps 4 to 8; safe to run again."""
	pe = frappe.get_doc("Payment Entry", payment_entry)
	if pe.docstatus != DocStatus.submitted() or not is_deposit(pe):
		return {}
	so_name = next((r.reference_name for r in pe.references if r.reference_doctype == SO), None)
	so_name = so_name or frappe.db.get_value(SO, {"sp_case": pe.sp_case, "docstatus": 1})
	so = frappe.get_doc(SO, so_name)
	station = frappe.get_doc(STATION, so.sp_station)
	first_time = not so.get("sp_deposit_payment")
	result = {
		"sales_order": so.name,
		"station": station.name,
		# reserve what the store holds first; then buy what is still not reserved
		"reservations": reserve_stock(so),
		"purchase_orders": draft_purchase_orders(so, station),
		"review_task": review_task(station),
	}
	mark_won(pe.sp_case, so)
	if first_time:
		frappe.db.set_value(SO, so.name, "sp_deposit_payment", pe.name, update_modified=False)
		_notify(station, so, pe)
	from smart_power.sp_stations.commission import DEPOSIT, at
	from smart_power.sp_stations.money import refresh

	refresh(station.name)
	result["referrer_commission"] = at(DEPOSIT, station.name)  # SP-177, when set to post here
	return result


# --- 4. draft purchase orders ----------------------------------------------------------------


def _available(item_code: str, warehouse: str) -> float:
	"""What the store can still promise: on hand less what is reserved for others."""
	bin_ = frappe.db.get_value(
		"Bin",
		{"item_code": item_code, "warehouse": warehouse},
		["actual_qty", "reserved_stock"],
		as_dict=True,
	)
	return max(flt(bin_.actual_qty) - flt(bin_.reserved_stock), 0.0) if bin_ else 0.0


def _default_supplier(item_code: str, company: str) -> str | None:
	return frappe.db.get_value(
		"Item Default", {"parent": item_code, "company": company}, "default_supplier"
	) or frappe.db.get_value("Item Default", {"parent": item_code}, "default_supplier")


def _reserved(so_name: str) -> dict:
	from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
		get_sre_reserved_qty_details_for_voucher,
	)

	return get_sre_reserved_qty_details_for_voucher(SO, so_name)


def _short(row, reserved: dict) -> float:
	"""What the line still lacks: neither reserved for it nor free in its store."""
	return flt(row.stock_qty) - flt(reserved.get(row.name)) - _available(row.item_code, row.warehouse)


def draft_purchase_orders(so, station) -> list[str]:
	"""One draft PO per default supplier for what the order still lacks; once per line."""
	reserved = _reserved(so.name)
	ordered = set(
		frappe.get_all(
			"Purchase Order Item",
			{"sales_order": so.name, "docstatus": ("<", DocStatus.cancelled())},
			pluck="sales_order_item",
		)
	)
	by_supplier: dict[str, list] = {}
	for row in so.items:
		if row.name in ordered or not frappe.get_cached_value("Item", row.item_code, "is_stock_item"):
			continue
		short = _short(row, reserved)
		if short <= 0:
			continue
		supplier = _default_supplier(row.item_code, so.company)
		if not supplier:
			continue  # listed on the review task instead
		by_supplier.setdefault(supplier, []).append((row, short))
	made = []
	for supplier, rows in sorted(by_supplier.items()):
		po = frappe.get_doc(
			{
				"doctype": PO,
				"supplier": supplier,
				"company": so.company,
				"transaction_date": today(),
				"schedule_date": add_days(today(), 1),
				"project": station.project,
				"sp_station": station.name,
				"sp_source": DEPOSIT_SOURCE,
				"set_warehouse": rows[0][0].warehouse,
				"items": [
					{
						"item_code": row.item_code,
						"qty": short / (flt(row.conversion_factor) or 1),
						"uom": row.uom,
						"conversion_factor": row.conversion_factor,
						"schedule_date": add_days(today(), 1),
						"warehouse": row.warehouse,
						"sales_order": so.name,
						"sales_order_item": row.name,
						"project": station.project,
					}
					for row, short in rows
				],
			}
		)
		po.flags.ignore_permissions = True
		po.insert()
		if station.execution_owner:
			# assigned to the projects manager (a ToDo, which marks the PO as assigned)
			frappe.get_doc(
				{
					"doctype": "ToDo",
					"allocated_to": station.execution_owner,
					"reference_type": PO,
					"reference_name": po.name,
					"description": _("Purchase for station {0}").format(station.name),
				}
			).insert(ignore_permissions=True)
		made.append(po.name)
	return made


def unsupplied_lines(so) -> list[str]:
	"""Stock lines short in the store with no default supplier: the review task lists them."""
	reserved = _reserved(so.name)
	return [
		row.item_code
		for row in so.items
		if frappe.get_cached_value("Item", row.item_code, "is_stock_item")
		and _short(row, reserved) > 0
		and not _default_supplier(row.item_code, so.company)
	]


# --- 5. stock reserved -------------------------------------------------------------------------


def reserve_stock(so) -> int:
	"""Reserve what the store holds for the order's lines (ERPNext skips what is reserved)."""
	from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
		create_stock_reservation_entries_for_so_items,
	)

	if not frappe.db.get_single_value("Stock Settings", "enable_stock_reservation"):
		return 0
	reserved = _reserved(so.name)
	items = []
	for row in so.items:
		if not frappe.get_cached_value("Item", row.item_code, "is_stock_item"):
			continue
		wanted = flt(row.stock_qty) - flt(reserved.get(row.name))
		qty = min(wanted, _available(row.item_code, row.warehouse))
		if qty > 0:
			if not row.reserve_stock:
				frappe.db.set_value("Sales Order Item", row.name, "reserve_stock", 1)
			items.append(
				{
					"sales_order_item": row.name,
					"item_code": row.item_code,
					"warehouse": row.warehouse,
					"qty_to_reserve": qty / (flt(row.conversion_factor) or 1),
				}
			)
	if not items:
		return 0
	before = frappe.db.count("Stock Reservation Entry", {"voucher_no": so.name, "docstatus": 1})
	create_stock_reservation_entries_for_so_items(frappe.get_doc(SO, so.name), items, notify=False)
	return frappe.db.count("Stock Reservation Entry", {"voucher_no": so.name, "docstatus": 1}) - before


# --- 6. the admin's technical review -------------------------------------------------------------


def review_task(station) -> str:
	existing = frappe.db.get_value(
		TASK, {"reference_doctype": STATION, "reference_name": station.name, "task_type": REVIEW_TASK}
	)
	if existing:
		return existing
	from smart_power.sp_sales.quote_request import _users_with

	so = frappe.get_doc(SO, station.sales_order)
	missing = unsupplied_lines(so)
	note = _("No default supplier for: {0}").format(", ".join(sorted(set(missing)))) if missing else ""
	admins = _users_with(ADMIN_ROLE) or ["Administrator"]
	task = frappe.get_doc(
		{
			"doctype": TASK,
			"subject": _("Technical review of station {0}").format(station.name),
			"task_type": REVIEW_TASK,
			"assigned_to": admins[0],
			"reference_doctype": STATION,
			"reference_name": station.name,
			"description": note,
		}
	).insert(ignore_permissions=True)
	return task.name


# --- 7. statuses -----------------------------------------------------------------------------------


def mark_won(case: str, so) -> None:
	"""The case Won, its approved version Approved, the case's other versions Superseded."""
	from smart_power.sp_sales.quotation import refresh_status

	approved = so.items[0].prevdoc_docname if so.items else None
	if approved:
		frappe.db.set_value(QUOTE, approved, "sp_is_approved", 1, update_modified=False)
		frappe.db.set_value(CASE, case, "accepted_quotation", approved, update_modified=False)
	for name in frappe.get_all(QUOTE, {"sp_case": case, "docstatus": 1}, pluck="name"):
		if name != approved:
			frappe.db.set_value(QUOTE, name, {"sp_superseded": 1, "sp_is_approved": 0}, update_modified=False)
		refresh_status(name)
	if frappe.db.get_value(CASE, case, "status") != "Won":
		# the deposit is the decision: no workflow step is skipped by hand, the money decided it
		doc = frappe.get_doc(CASE, case)
		doc.db_set({"status": "Won", "won_on": today()})
		doc.add_comment("Info", _("Won: the deposit was confirmed."))


# --- 8. notifications --------------------------------------------------------------------------------


def _notify(station, so, pe) -> None:
	from smart_power.notify import send
	from smart_power.sp_sales.quote_request import _users_with

	users = sorted({u for u in [station.execution_owner, *_users_with(ADMIN_ROLE)] if u})
	if not users:
		return
	send(
		"won_case",
		users,
		STATION,
		station.name,
		_("Deposit confirmed for {0}: station {1}, contract {2}").format(
			station.customer_name or station.customer, station.name, so.name
		),
		from_user=frappe.session.user,
	)
