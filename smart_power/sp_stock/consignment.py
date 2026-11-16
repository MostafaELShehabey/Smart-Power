"""Africa System consignment by quantity, outside the stock ledger (SP-91; decision 46; tech plan
6-11-2026 section 3 rule 6: ERPNext has no supplier consignment, and the supplier's goods must
never enter company stock value).

    container   supplier, item, pallets x panels per pallet, received on, where it is kept
    movements   Reserve (for a named customer or a station) · Hand over (to the supplier's
                customer, with a delivery note) · Withdraw by PO (SP-92: the panels become company
                stock through a Purchase Receipt) · Return to supplier

    balance   = received - withdrawn - handed over - returned
    available = balance - reserved (open reservations); a hand-over clears its reservation

No Stock Ledger Entry and no GL come from containers or movements (only a withdrawal's Purchase
Receipt, SP-92, and the storage fee below post). A container at or under the low-balance threshold
(settings) alerts the admin and the main store keeper once. The storage fee the supplier pays is
income (Storage Fees), deducted from the supplier's balance or paid into an official account.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, today

CONTAINER, MOVEMENT = "SP Consignment Container", "SP Consignment Movement"
RESERVE, HAND_OVER, WITHDRAW, RETURN = "Reserve", "Hand over", "Withdraw by PO", "Return to supplier"
OPEN, LOW, EMPTY = "Open", "Low", "Empty"
DONE, RES_OPEN, CLEARED, CANCELLED = "Done", "Open", "Cleared", "Cancelled"
DEDUCTED = "Deducted from the supplier's balance"
FEE_ACCOUNT = "Storage Fees"
ALERT_ROLES = ("SP Admin", "SP Main Store Keeper")
FEE_ROLES = ("SP Admin", "System Manager", "SP Accountant")


# --- the container ---------------------------------------------------------------------------------


def validate_container(doc) -> None:
	doc.company = doc.company or _default_company()
	if cint(doc.pallets) <= 0 or cint(doc.per_pallet) <= 0:
		frappe.throw(_("Enter the pallets and the panels per pallet."))
	if not frappe.db.get_value("Supplier", doc.supplier, "sp_is_consignment_owner"):
		frappe.throw(_("{0} does not keep goods with us on consignment.").format(frappe.bold(doc.supplier)))
	doc.received_qty = cint(doc.pallets) * cint(doc.per_pallet)
	_totals(doc)
	if cint(doc.balance_qty) < 0:
		frappe.throw(_("More has left this container than it received."))


def _totals(doc) -> None:
	rows = (
		frappe.get_all(
			MOVEMENT,
			{"container": doc.name, "docstatus": 1},
			["movement_type", "qty", "cleared_qty", "status"],
		)
		if not doc.is_new()
		else []
	)

	def total(kind):
		return sum(cint(r.qty) for r in rows if r.movement_type == kind)

	doc.withdrawn_qty, doc.handed_over_qty, doc.returned_qty = (
		total(WITHDRAW),
		total(HAND_OVER),
		total(RETURN),
	)
	doc.reserved_qty = sum(
		max(cint(r.qty) - cint(r.cleared_qty), 0)
		for r in rows
		if r.movement_type == RESERVE and r.status == RES_OPEN
	)
	doc.balance_qty = cint(doc.received_qty) - doc.withdrawn_qty - doc.handed_over_qty - doc.returned_qty
	doc.available_qty = doc.balance_qty - doc.reserved_qty
	doc.status = EMPTY if doc.balance_qty <= 0 else LOW if doc.balance_qty <= _threshold() else OPEN


def _threshold() -> int:
	from smart_power.sp_core.services.settings import get_value

	return cint(get_value("consignment_low_balance"))


def refresh(name: str) -> None:
	"""Recompute the container's quantities and status; alert once when it turns low."""
	doc = frappe.get_doc(CONTAINER, name)
	before = doc.status
	_totals(doc)
	frappe.db.set_value(
		CONTAINER,
		name,
		{
			k: doc.get(k)
			for k in (
				"withdrawn_qty",
				"handed_over_qty",
				"returned_qty",
				"reserved_qty",
				"balance_qty",
				"available_qty",
				"status",
			)
		},
	)
	if doc.status in (LOW, EMPTY) and before == OPEN:
		_alert_low(doc)


def _alert_low(doc) -> None:
	from smart_power.notify import send
	from smart_power.sp_sales.quote_request import _users_with

	users = set()
	for role in ALERT_ROLES:
		users |= set(_users_with(role))
	send(
		"consignment_low",
		sorted(users),
		CONTAINER,
		doc.name,
		_("Consignment container {0} ({1}) is down to {2} panels").format(
			doc.container_no or doc.name, doc.item_name or doc.item, doc.balance_qty
		),
		from_user="Administrator",
	)


def _default_company() -> str | None:
	from smart_power.sp_core.services.company import COMPANY_SETTINGS

	return frappe.db.get_single_value(COMPANY_SETTINGS, "company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)


# --- movements ------------------------------------------------------------------------------------


def validate_movement(doc) -> None:
	container = frappe.get_doc(CONTAINER, doc.container)
	doc.item, doc.supplier = container.item, container.supplier
	if cint(doc.qty) <= 0:
		frappe.throw(_("The quantity must be above zero."))
	if doc.docstatus.is_draft():
		doc.status = "Draft"
	reserved_here = 0
	if doc.reservation:
		res = frappe.db.get_value(
			MOVEMENT,
			doc.reservation,
			["container", "movement_type", "status", "qty", "cleared_qty"],
			as_dict=True,
		)
		if (
			not res
			or res.container != doc.container
			or res.movement_type != RESERVE
			or res.status != RES_OPEN
		):
			frappe.throw(_("{0} is not an open reservation on this container.").format(doc.reservation))
		reserved_here = cint(res.qty) - cint(res.cleared_qty)
	if doc.movement_type == WITHDRAW and not doc.flags.sp_from_po:
		frappe.throw(
			_("Withdraw from the container with Withdraw by PO, so the panels are bought into company stock.")
		)
	if doc.movement_type in (RESERVE, HAND_OVER) and not (doc.customer_name or doc.station):
		frappe.throw(_("Name the customer or the station."))
	if doc.movement_type == RESERVE and doc.reservation:
		frappe.throw(_("A reservation cannot clear another reservation."))
	if doc.docstatus.is_draft() and cint(doc.qty) > cint(container.available_qty) + reserved_here:
		frappe.throw(
			_("Only {0} panels are available in {1} ({2} reserved).").format(
				cint(container.available_qty) + reserved_here,
				container.container_no or container.name,
				cint(container.reserved_qty) - reserved_here,
			)
		)


def on_movement_submit(doc) -> None:
	doc.db_set("status", RES_OPEN if doc.movement_type == RESERVE else DONE)
	if doc.reservation:
		_clear(doc.reservation, cint(doc.qty))
	refresh(doc.container)


def on_movement_cancel(doc) -> None:
	if doc.movement_type == RESERVE and cint(doc.cleared_qty):
		frappe.throw(_("Part of this reservation was handed over; cancel that hand-over first."))
	doc.db_set("status", CANCELLED)
	if doc.reservation:
		_clear(doc.reservation, -cint(doc.qty))
	refresh(doc.container)


def _clear(reservation: str, qty: int) -> None:
	res = frappe.db.get_value(MOVEMENT, reservation, ["qty", "cleared_qty"], as_dict=True)
	cleared = min(max(cint(res.cleared_qty) + qty, 0), cint(res.qty))
	frappe.db.set_value(
		MOVEMENT,
		reservation,
		{"cleared_qty": cleared, "status": CLEARED if cleared >= cint(res.qty) else RES_OPEN},
	)


@frappe.whitelist(methods=["POST"])
def make_movement(container: str, movement_type: str, qty: int, **values) -> str:
	"""Reserve, hand over or return from the container's buttons (submitted at once)."""
	if movement_type not in (RESERVE, HAND_OVER, RETURN):
		frappe.throw(_("Choose Reserve, Hand over or Return to supplier."))
	allowed = ("customer_name", "customer_phone", "station", "reservation", "note", "movement_date")
	doc = frappe.get_doc(
		{
			"doctype": MOVEMENT,
			"container": container,
			"movement_type": movement_type,
			"qty": cint(qty),
			**{k: values[k] for k in allowed if values.get(k)},
		}
	)
	doc.insert()
	doc.submit()
	return doc.name


@frappe.whitelist()
def open_reservations(container: str) -> list[dict]:
	return frappe.get_list(
		MOVEMENT,
		{"container": container, "movement_type": RESERVE, "status": RES_OPEN, "docstatus": 1},
		["name", "qty", "cleared_qty", "customer_name", "station"],
		order_by="movement_date asc",
	)


# --- the storage fee (decision 46) ------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def record_fee(
	container: str,
	amount: float,
	settled_by: str,
	account: str | None = None,
	fee_date: str | None = None,
	note: str | None = None,
) -> str:
	"""The storage fee the supplier pays: income (Storage Fees), off their balance or paid in."""
	if frappe.session.user != "Administrator" and not set(FEE_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin or the accountant records a storage fee."), frappe.PermissionError)
	doc = frappe.get_doc(CONTAINER, container)
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("The amount must be above zero."))
	company = doc.company
	income = frappe.db.get_value("Account", {"company": company, "account_name": FEE_ACCOUNT, "is_group": 0})
	if not income:
		frappe.throw(_("Company {0} has no {1} account.").format(company, FEE_ACCOUNT))
	debit = {"debit_in_account_currency": amount}
	if settled_by == DEDUCTED:
		from erpnext.accounts.party import get_party_account

		debit.update(
			account=get_party_account("Supplier", doc.supplier, company),
			party_type="Supplier",
			party=doc.supplier,
		)
	else:
		if frappe.db.get_value("Account", account, "sp_account_kind") != "Official":
			frappe.throw(_("Choose the official account the fee was paid into."))
		debit["account"] = account
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": company,
			"posting_date": fee_date or today(),
			"user_remark": _("Storage fee for consignment container {0}").format(
				doc.container_no or doc.name
			),
			"sp_posting_event": "Storage Fee",
			"sp_source_doctype": CONTAINER,
			"sp_source_name": doc.name,
			"accounts": [debit, {"account": income, "credit_in_account_currency": amount}],
		}
	)
	je.flags.ignore_permissions = True
	# ERPNext suggests "Is Advance" for any supplier debit; the fee is not an advance (errors still raise)
	muted, frappe.flags.mute_messages = frappe.flags.mute_messages, True
	try:
		je.insert()
		je.submit()
	finally:
		frappe.flags.mute_messages = muted
	doc.append(
		"fees",
		{
			"fee_date": fee_date or today(),
			"amount": amount,
			"settled_by": settled_by,
			"account": debit["account"] if settled_by != DEDUCTED else None,
			"note": note,
			"journal_entry": je.name,
		},
	)
	doc.flags.ignore_permissions = True
	doc.save()
	return je.name


# --- withdraw by PO (SP-92) -------------------------------------------------------------------------

WITHDRAW_ROLES = ("SP Admin", "System Manager", "SP Purchase Officer")


@frappe.whitelist(methods=["POST"])
def withdraw(
	container: str,
	qty: int,
	watt_price: float,
	warehouse: str | None = None,
	station: str | None = None,
	price_date: str | None = None,
	reservation: str | None = None,
	panel_watts: float | None = None,
) -> dict:
	"""Buy panels out of the container into company stock, at the day's watt price.

	A Purchase Order (a consignment conversion) at watt price x panel watts, its Purchase Receipt
	into the company warehouse (a station's site warehouse, with its project), and the Purchase
	Invoice that makes the supplier payable; the container balance drops by the withdrawal."""
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

	from smart_power.sp_core.review_centre import raise_item
	from smart_power.sp_stock.warehouses import site_warehouse

	if frappe.session.user != "Administrator" and not set(WITHDRAW_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin or purchasing withdraws from consignment."), frappe.PermissionError)
	doc = frappe.get_doc(CONTAINER, container)
	qty, watt_price = cint(qty), flt(watt_price)
	watts = flt(panel_watts) or flt(frappe.db.get_value("Item", doc.item, "sp_watt"))
	if qty <= 0 or watt_price <= 0:
		frappe.throw(_("Enter the quantity and the day's watt price."))
	if watts <= 0:
		frappe.throw(_("Enter the panel's watts (or set Power (W) on item {0}).").format(doc.item))
	reserved_here = 0
	if reservation:
		res = frappe.db.get_value(MOVEMENT, reservation, ["qty", "cleared_qty", "container"], as_dict=True)
		reserved_here = cint(res.qty) - cint(res.cleared_qty) if res and res.container == doc.name else 0
	if qty > cint(doc.available_qty) + reserved_here:
		frappe.throw(
			_("Only {0} panels are available in {1}.").format(
				cint(doc.available_qty) + reserved_here, doc.container_no or doc.name
			)
		)
	project = None
	if station:
		project = frappe.db.get_value("SP Station", station, "project")
		warehouse = warehouse or site_warehouse(project)
	if not warehouse:
		frappe.throw(_("Choose the company warehouse the panels go to."))
	if frappe.db.get_value("Warehouse", warehouse, "company") != doc.company:
		frappe.throw(_("Warehouse {0} is not {1}'s.").format(warehouse, doc.company))
	when = price_date or today()
	rate = watt_price * watts
	po = frappe.get_doc(
		{
			"doctype": "Purchase Order",
			"supplier": doc.supplier,
			"company": doc.company,
			# the watt price is in the company's own currency
			"currency": frappe.get_cached_value("Company", doc.company, "default_currency"),
			"conversion_rate": 1,
			"disable_rounded_total": 1,  # the supplier is owed exactly panels x watts x price
			"transaction_date": when,
			"schedule_date": when,
			"set_warehouse": warehouse,
			"project": project,
			"sp_is_consignment_conversion": 1,
			"sp_consignment_container": doc.name,
			"sp_watt_price": watt_price,
			"sp_price_date": when,
			"items": [
				{
					"item_code": doc.item,
					"qty": qty,
					"rate": rate,
					"warehouse": warehouse,
					"schedule_date": when,
					"project": project,
				}
			],
		}
	)
	po.flags.ignore_permissions = True
	po.insert()
	po.submit()
	movement = frappe.get_doc(
		{
			"doctype": MOVEMENT,
			"container": doc.name,
			"movement_type": WITHDRAW,
			"qty": qty,
			"movement_date": when,
			"station": station,
			"reservation": reservation,
			"purchase_order": po.name,
			"note": _("{0} W x {1} per W").format(watts, watt_price),
		}
	)
	movement.flags.sp_from_po = True
	movement.flags.ignore_permissions = True
	movement.insert()
	movement.submit()
	pr = make_purchase_receipt(po.name)
	pr.posting_date = when
	pr.set_posting_time = 1
	pr.flags.ignore_permissions = True
	pr.insert()
	pr.submit()  # until receipt confirmation (P4, SP-85) adds its own step
	movement.db_set("purchase_receipt", pr.name)
	pi = _invoice_from_receipt(pr, po, when)
	raise_item(
		"Consignment Conversion",
		po,
		_("{0} x {1} from consignment at {2} per W ({3})").format(
			qty, doc.item_name or doc.item, watt_price, doc.supplier
		),
		amount=flt(po.grand_total),
	)
	return {
		"purchase_order": po.name,
		"purchase_receipt": pr.name,
		"purchase_invoice": pi.name,
		"movement": movement.name,
		"amount": flt(po.grand_total),
	}


def _invoice_from_receipt(pr, po, when):
	"""The supplier's bill for the receipt: the purchasing user may not create invoices
	themselves (ERPNext's mapper checks), so it is built from the receipt's rows."""
	srbnb = frappe.get_cached_value("Company", pr.company, "stock_received_but_not_billed")
	pi = frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"supplier": pr.supplier,
			"company": pr.company,
			"posting_date": when,
			"set_posting_time": 1,
			"bill_no": po.name,
			"bill_date": when,
			"disable_rounded_total": 1,
			"project": pr.get("project"),
			"currency": pr.currency,
			"conversion_rate": pr.conversion_rate,
			"buying_price_list": pr.buying_price_list,
			"items": [
				{
					"item_code": row.item_code,
					"qty": row.qty,
					"rate": row.rate,
					"uom": row.uom,
					"stock_uom": row.stock_uom,
					"conversion_factor": row.conversion_factor,
					"warehouse": row.warehouse,
					"project": row.project,
					"cost_center": row.cost_center,
					# a received stock item is billed against Stock Received But Not Billed
					"expense_account": srbnb,
					"purchase_receipt": pr.name,
					"pr_detail": row.name,
					"purchase_order": row.purchase_order,
					"po_detail": row.purchase_order_item,
				}
				for row in pr.items
			],
		}
	)
	pi.flags.ignore_permissions = True  # checked by withdraw: the admin or purchasing
	pi.set_missing_values()
	pi.insert()
	pi.submit()
	return pi


@frappe.whitelist()
def withdraw_options(container: str) -> dict:
	"""What the Withdraw dialog offers: the panel's watts and the company's stock warehouses."""
	from smart_power.sp_stock.warehouses import MAIN, SHOWROOM, warehouse_of

	doc = frappe.get_doc(CONTAINER, container)
	return {
		"panel_watts": flt(frappe.db.get_value("Item", doc.item, "sp_watt")),
		"warehouses": [
			w for w in (warehouse_of(doc.company, MAIN), warehouse_of(doc.company, SHOWROOM)) if w
		],
		"company": doc.company,
	}
