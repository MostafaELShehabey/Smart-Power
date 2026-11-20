"""S3 Change order (SP-78): scope changes after the contract is signed.

A change order adds lines to the contract or returns them (a negative quantity), with the
customer's approval file and a reason. On submit:

    1. the contract (the submitted Sales Order) is updated through ERPNext's Update Items;
    2. its payment schedule takes the change, by `schedule_mode`:
           Spread over remaining   shared out over the instalments not paid yet
           New installment         an addition becomes one more instalment on its date
           Reduce last             a reduction comes off the last unpaid instalments first
    3. the station's money is refreshed (agreed, remaining, next due, instalment status);
    4. its estimated cost (the snapshot frozen at the deposit) takes the change's cost, listed
       apart under "change_orders" (an estimate, not actual cost);
    5. the admin sees it in the review centre (RV2, Change orders).

The Agreement tab is never edited directly. A returned line is valued at the contract's price
for that item (owner, 2026-11-21). A change that lowers the agreed amount by more than is still
unpaid is refused: the customer is refunded first (owner, 2026-11-21). A submitted change order
is not cancelled; another change order reverses it.

Installments are the Sales Order's Payment Schedule rows (ERD 7.1, 8-11-2026 note).
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, today

from smart_power.sp_stations.station_workflow import CANCELLED, FIN_CLOSED, TECH_CLOSED

CHANGE_ORDER, STATION, SO, SO_ITEM, ROW = (
	"SP Change Order",
	"SP Station",
	"Sales Order",
	"Sales Order Item",
	"Payment Schedule",
)
SPREAD, NEW_INSTALLMENT, REDUCE_LAST = "Spread over remaining", "New installment", "Reduce last"
CLOSED = (TECH_CLOSED, FIN_CLOSED, CANCELLED)
REVIEW_CATEGORY = "Change Order"
ROUNDING = 0.005  # sp-allow-number: half a piastre
MONEY_DIGITS = 2  # sp-allow-number: piastres
SUBMITTED = 1  # sp-allow-number: docstatus
PERCENT = 100  # sp-allow-number: invoice portion is a percentage


def _contract_lines(sales_order: str) -> list:
	return frappe.get_all(
		SO_ITEM,
		{"parent": sales_order, "parenttype": SO},
		["name", "idx", "item_code", "qty", "rate", "delivered_qty"],
		order_by="idx asc",
	)


def _price(item_code: str, customer: str | None) -> frappe._dict:
	from smart_power.sp_stock.prices import get_price

	tier = (customer and frappe.db.get_value("Customer", customer, "sp_tier")) or "Individual"
	return get_price(item_code, tier if tier in ("Individual", "Company") else "Individual")


def _snapshot_cost(station, item_code: str) -> float | None:
	snapshot = json.loads(station.estimated_cost_snapshot or "{}")
	return next(
		(flt(r.get("cost")) for r in snapshot.get("lines") or [] if r.get("item_code") == item_code), None
	)


def validate(doc) -> None:
	station = frappe.get_doc(STATION, doc.station)
	if station.status in CLOSED:
		frappe.throw(
			_("Station {0} is {1}: its contract no longer changes.").format(station.name, _(station.status))
		)
	if not station.sales_order or frappe.db.get_value(SO, station.sales_order, "docstatus") != SUBMITTED:
		frappe.throw(
			_("The contract of station {0} is not signed yet: change the draft contract instead.").format(
				station.name
			)
		)
	doc.sales_order, doc.company, doc.customer_name = (
		station.sales_order,
		station.company,
		station.customer_name,
	)
	_price_lines(doc, station)
	doc.delta_amount = flt(sum(flt(line.amount) for line in doc.items), MONEY_DIGITS)
	doc.cost_delta = flt(sum(flt(line.qty) * flt(line.cost) for line in doc.items), MONEY_DIGITS)
	_check_schedule(doc, station)
	if doc.docstatus == 0:  # what the contract becomes; the real figures are set on submit
		doc.agreed_before = station.agreed_amount
		doc.agreed_after = flt(station.agreed_amount) + flt(doc.delta_amount)


def _price_lines(doc, station) -> None:
	lines = _contract_lines(station.sales_order)
	taken: dict[str, float] = {}  # returned so far from each contract line in this change order
	for line in doc.items:
		qty = flt(line.qty)
		if not qty:
			frappe.throw(_("Row {0}: type a quantity (negative to return it).").format(line.idx))
		if qty < 0:
			match = _returnable(lines, line, -qty, taken)
			if not match:
				frappe.throw(
					_("Row {0}: {1} is not on the contract, or fewer than {2} are left on it.").format(
						line.idx, frappe.bold(line.item_code), -qty
					)
				)
			taken[match.name] = taken.get(match.name, 0) - qty
			line.so_detail = match.name
			line.rate = match.rate  # a return is valued at the contract's price (owner, 2026-11-21)
		else:
			line.so_detail = None
			if not flt(line.rate):
				line.rate = flt(_price(line.item_code, station.customer).price)
			if not flt(line.rate):
				frappe.throw(
					_("Row {0}: {1} has no price: type its rate.").format(
						line.idx, frappe.bold(line.item_code)
					)
				)
		if not flt(line.cost):
			line.cost = _snapshot_cost(station, line.item_code) if qty < 0 else None
			line.cost = flt(
				line.cost if line.cost is not None else _price(line.item_code, station.customer).cost
			)
		line.amount = flt(qty * flt(line.rate), MONEY_DIGITS)


def _returnable(lines: list, line, qty: float, taken: dict):
	"""The contract line a return comes off: the one it names, else the first of that item with
	enough left (what is delivered stays)."""
	for row in lines:
		if line.so_detail and row.name != line.so_detail:
			continue
		if row.item_code != line.item_code:
			continue
		left = flt(row.qty) - flt(row.delivered_qty) - taken.get(row.name, 0)
		if left >= qty - ROUNDING:
			return row
	return None


def _check_schedule(doc, station) -> None:
	from smart_power.sp_stations.installments import allocation

	delta = flt(doc.delta_amount)
	if doc.schedule_mode == REDUCE_LAST and delta > 0:
		frappe.throw(_("Reduce Last is for a reduction: spread an addition, or add it as a new installment."))
	if doc.schedule_mode == NEW_INSTALLMENT:
		if delta < 0:
			frappe.throw(
				_("A new installment is for an addition: spread a reduction, or take it from the last.")
			)
		if not doc.new_installment_date:
			frappe.throw(_("Choose the date of the new installment."), frappe.MandatoryError)
	unpaid = [r for r in allocation(station) if r["left"] > ROUNDING]
	if doc.schedule_mode == SPREAD and delta > 0 and not unpaid:
		frappe.throw(_("Every installment is paid: add the change as a new installment."))
	left = sum(r["left"] for r in unpaid)
	if delta < 0 and -delta > left + ROUNDING:
		frappe.throw(
			_(
				"This change lowers the agreed amount by {0}, but only {1} is still unpaid. Refund the customer first, then record the change."
			).format(frappe.format(-delta, "Currency"), frappe.format(left, "Currency")),
			title=_("The customer would be over-paid"),
		)


# ---------------------------------------------------------------- submit


def on_submit(doc) -> None:
	from smart_power.sp_core.review_centre import raise_item
	from smart_power.sp_stations.installments import allocate, allocation
	from smart_power.sp_stations.money import refresh

	station = frappe.get_doc(STATION, doc.station)
	old_rows = allocation(station)  # the schedule as it stood, with what is paid of each row
	before = _contract_total(station.sales_order)
	_update_contract(doc)
	after = _contract_total(station.sales_order)
	delta = flt(after - before, MONEY_DIGITS)
	_reschedule(station.sales_order, old_rows, delta, doc, after)
	doc.db_set({"agreed_before": before, "agreed_after": after, "delta_amount": delta})
	_add_to_estimate(station, doc)
	refresh(station.name)
	allocate(station.name)
	summary = _("Change order {0} on station {1}: {2} ({3})").format(
		doc.name, station.name, frappe.format(delta, "Currency"), doc.reason
	)
	raise_item(REVIEW_CATEGORY, doc, summary, amount=delta)
	station.add_comment("Info", summary)


def before_cancel(doc) -> None:
	frappe.throw(
		_("A submitted change order is not cancelled: record another change order that reverses it.")
	)


def _contract_total(sales_order: str) -> float:
	total, grand = frappe.db.get_value(SO, sales_order, ["rounded_total", "grand_total"])
	return flt(total or grand)


def _update_contract(doc) -> None:
	"""The contract's lines with the change, through ERPNext's Update Items, as the user: who
	submits a change order may change the contract (the contract manager and the admin)."""
	from erpnext.controllers.accounts_controller import update_child_qty_rate

	so = frappe.get_doc(SO, doc.sales_order)
	rows = {
		r.name: {
			"docname": r.name,
			"idx": r.idx,
			"item_code": r.item_code,
			"qty": flt(r.qty),
			"rate": flt(r.rate),
			"uom": r.uom,
			"conversion_factor": r.conversion_factor,
			"delivery_date": str(r.delivery_date) if r.delivery_date else None,
		}
		for r in so.items
	}
	added = []
	for line in doc.items:
		if flt(line.qty) < 0:
			rows[line.so_detail]["qty"] += flt(line.qty)
			continue
		same = next(
			(
				r
				for r in rows.values()
				if r["item_code"] == line.item_code and abs(r["rate"] - flt(line.rate)) < ROUNDING
			),
			None,
		)
		if same:
			same["qty"] += flt(line.qty)
		else:
			added.append(
				{
					"item_code": line.item_code,
					"qty": flt(line.qty),
					"rate": flt(line.rate),
					"uom": frappe.db.get_value("Item", line.item_code, "stock_uom"),
					"conversion_factor": 1,
					"delivery_date": str(so.delivery_date or today()),
				}
			)
	trans = [r for r in rows.values() if r["qty"] > ROUNDING] + added
	for idx, row in enumerate(trans, start=1):
		row["idx"] = idx
	update_child_qty_rate(SO, json.dumps(trans), so.name)


def _reschedule(sales_order: str, old_rows: list, delta: float, doc, total: float) -> None:
	"""The schedule as it stood plus the change, by the change order's mode. ERPNext's Update
	Items rescaled every row to the new total (paid ones too); each row is set again here."""
	amounts = {r["name"]: flt(r["payment_amount"]) for r in old_rows}
	unpaid = [r for r in old_rows if r["left"] > ROUNDING]
	new_row = None
	if doc.schedule_mode == NEW_INSTALLMENT and delta > 0:
		new_row = delta
	elif doc.schedule_mode == REDUCE_LAST and delta < 0:
		need = -delta
		for r in reversed(unpaid):
			take = min(r["left"], need)
			amounts[r["name"]] -= take
			need -= take
	elif delta > 0:
		share = flt(delta / len(unpaid), MONEY_DIGITS)
		for r in unpaid:
			amounts[r["name"]] += share
		amounts[unpaid[-1]["name"]] += flt(delta - share * len(unpaid), MONEY_DIGITS)
	elif delta < 0:
		_spread_reduction(amounts, unpaid, -delta)
	conversion = flt(frappe.db.get_value(SO, sales_order, "conversion_rate")) or 1
	for name, amount in amounts.items():
		amount = flt(amount, MONEY_DIGITS)
		paid = flt(frappe.db.get_value(ROW, name, "paid_amount"))
		if amount <= ROUNDING and not paid:
			frappe.db.delete(ROW, {"name": name})  # an instalment the change took away entirely
			continue
		frappe.db.set_value(
			ROW,
			name,
			{
				"payment_amount": amount,
				"base_payment_amount": flt(amount * conversion, MONEY_DIGITS),
				"invoice_portion": amount / total * PERCENT if total else 0,
				"outstanding": flt(amount - paid, MONEY_DIGITS),
				"base_outstanding": flt((amount - paid) * conversion, MONEY_DIGITS),
			},
			update_modified=False,
		)
	if new_row:
		count = frappe.db.count(ROW, {"parent": sales_order, "parenttype": SO})
		frappe.get_doc(
			{
				"doctype": ROW,
				"parent": sales_order,
				"parenttype": SO,
				"parentfield": "payment_schedule",
				"idx": count + 1,
				"docstatus": SUBMITTED,
				"due_date": doc.new_installment_date,
				"description": _("Change order {0}").format(doc.name),
				"payment_amount": new_row,
				"base_payment_amount": flt(new_row * conversion, MONEY_DIGITS),
				"invoice_portion": new_row / total * PERCENT if total else 0,
				"outstanding": new_row,
				"base_outstanding": flt(new_row * conversion, MONEY_DIGITS),
			}
		).db_insert()
	_renumber(sales_order)


def _spread_reduction(amounts: dict, unpaid: list, need: float) -> None:
	"""A reduction shared out over the unpaid instalments; one that has less left than its share
	gives what it has, and the rest is shared over the others."""
	room = {r["name"]: r["left"] for r in unpaid}
	while need > ROUNDING and room:
		share = need / len(room)
		for name in list(room):
			take = min(room[name], share)
			amounts[name] -= take
			room[name] -= take
			need -= take
			if room[name] <= ROUNDING:
				room.pop(name)


def _renumber(sales_order: str) -> None:
	rows = frappe.get_all(
		ROW, {"parent": sales_order, "parenttype": SO}, pluck="name", order_by="due_date asc, idx asc"
	)
	for idx, name in enumerate(rows, start=1):
		frappe.db.set_value(ROW, name, "idx", idx, update_modified=False)


def _add_to_estimate(station, doc) -> None:
	"""The frozen estimate takes the change's cost, listed apart (an estimate, not actual cost)."""
	snapshot = json.loads(station.estimated_cost_snapshot or "{}")
	snapshot.setdefault("change_orders", []).append(
		{
			"name": doc.name,
			"date": str(doc.posting_date),
			"added_on": str(now_datetime()),
			"lines": [
				{"item_code": r.item_code, "qty": flt(r.qty), "rate": flt(r.rate), "cost": flt(r.cost)}
				for r in doc.items
			],
			"cost": flt(doc.cost_delta),
		}
	)
	snapshot["total_cost"] = flt(snapshot.get("total_cost")) + flt(doc.cost_delta)
	frappe.db.set_value(
		STATION, station.name, "estimated_cost_snapshot", json.dumps(snapshot), update_modified=False
	)


def of_station(station: str) -> list[dict]:
	"""The station's change orders with their lines, for the station record's Scope tab (SP-76)."""
	orders = frappe.get_all(
		CHANGE_ORDER,
		{"station": station, "docstatus": ("<", 2)},  # sp-allow-number: docstatus 2 is cancelled
		["name", "posting_date", "docstatus", "delta_amount", "reason"],
		order_by="posting_date asc, creation asc",
	)
	for order in orders:
		order.lines = frappe.get_all(
			"SP Change Order Item",
			{"parent": order.name, "parenttype": CHANGE_ORDER},
			["item_code", "item_name", "qty"],
			order_by="idx asc",
		)
	return orders
