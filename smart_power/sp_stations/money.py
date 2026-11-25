"""A station's money chips (SP-73): Agreed · Paid (confirmed only) · Remaining · Next due.

    refresh(station) -> {agreed, paid, written_off, remaining, next_due_date, next_due_amount}

- Agreed: the contract (Sales Order, SP-74) once it exists, else the accepted quote's total.
  Change orders (SP-78) update the contract.
- Paid: confirmed customer payments only, less the confirmed refunds of a cancelled station
  (SP-176). A payment is confirmed when its Payment Entry is submitted (the admin's confirmation,
  SP-114/SP-115); it carries the station's project. An opening station (SP-160) adds what was
  paid before go-live (opening_paid_amount).
- Remaining: agreed - paid - written off; nothing on a cancelled station (BUG-26).
- Next due: the first instalment of the payment schedule (the contract's, else the accepted
  quote's) that the paid and written-off money does not cover yet; none on a cancelled station.

Called when a station opens, when a payment is confirmed or reversed (Payment Entry hooks),
and by change orders and write-offs.
"""

import frappe
from frappe.model.docstatus import DocStatus
from frappe.utils import flt, getdate

from smart_power.sp_stations.station_workflow import CANCELLED

STATION = "SP Station"


def _agreed_and_schedule(doc) -> tuple[float, list]:
	for doctype, name in (("Sales Order", doc.sales_order), ("Quotation", doc.quotation_accepted)):
		if name and frappe.db.exists(doctype, {"name": name, "docstatus": ("<", DocStatus.cancelled())}):
			source = frappe.get_doc(doctype, name)
			total = flt(source.get("rounded_total") or source.get("grand_total"))
			schedule = sorted(
				(
					(getdate(r.due_date), flt(r.payment_amount))
					for r in source.get("payment_schedule") or []
					if r.due_date
				),
				key=lambda r: r[0],
			)
			return total, schedule
	return flt(doc.agreed_amount), []


def confirmed_payments(project: str | None) -> float:
	"""Customer money received on the station's project, confirmed (submitted) only."""
	if not project:
		return 0.0
	rows = frappe.get_all(
		"Payment Entry",
		filters={"project": project, "docstatus": 1, "payment_type": "Receive", "party_type": "Customer"},
		pluck="paid_amount",
	)
	return sum(flt(r) for r in rows)


def confirmed_refunds(project: str | None) -> float:
	"""Customer money paid back on the station's project (SP-176 refunds), confirmed only."""
	if not project:
		return 0.0
	rows = frappe.get_all(
		"Payment Entry",
		filters={
			"project": project,
			"docstatus": 1,
			"payment_type": "Pay",
			"party_type": "Customer",
			"sp_refund_of": ("is", "set"),
		},
		pluck="paid_amount",
	)
	return sum(flt(r) for r in rows)


def next_due(schedule: list, covered: float) -> tuple:
	"""The first instalment the covered money does not pay in full, and what is left of it."""
	cumulative = 0.0
	for due_date, amount in schedule:
		cumulative += amount
		if cumulative > covered + 0.005:  # sp-allow-number: half a piastre, rounding
			return due_date, min(amount, cumulative - covered)
	return None, 0.0


def pending_payments(station: str) -> float:
	"""Recorded customer payments waiting for the admin's confirmation (SP-114)."""
	rows = frappe.get_all(
		"SP Customer Payment", {"station": station, "status": "Pending", "docstatus": 1}, pluck="amount"
	)
	return sum(flt(r) for r in rows)


def compute(doc) -> dict:
	agreed, schedule = _agreed_and_schedule(doc)
	# with what was paid before go-live, when the opening took it as paid (SP-160)
	paid = (
		confirmed_payments(doc.project) - confirmed_refunds(doc.project) + flt(doc.get("opening_paid_amount"))
	)
	written_off = flt(doc.write_off_amount)
	due_date, due_amount = next_due(schedule, paid + written_off)
	remaining = max(agreed - paid - written_off, 0.0)
	if doc.status == CANCELLED:  # the customer owes nothing on a cancelled station (BUG-26)
		remaining, due_date, due_amount = 0.0, None, 0.0
	return {
		"agreed_amount": agreed,
		"paid_amount": paid,
		"pending_amount": pending_payments(doc.name),
		"remaining_amount": remaining,
		"next_due_date": due_date,
		"next_due_amount": due_amount,
	}


def refresh(station: str) -> dict:
	"""Recompute and store the station's money figures."""
	from smart_power.sp_stations.installments import allocate

	doc = frappe.get_doc(STATION, station)
	values = compute(doc)
	frappe.db.set_value(STATION, station, values, update_modified=False)
	doc.update(values)
	allocate(doc)  # the instalments' paid and status follow the money (SP-81)
	return {**values, "write_off_amount": flt(doc.write_off_amount)}


def on_payment(doc, method=None) -> None:
	"""Payment Entry on_submit / on_cancel: the station of its project refreshes."""
	if not doc.get("project"):
		return
	from smart_power.sp_stations.close import settle

	for station in frappe.get_all(STATION, {"project": doc.project}, pluck="name"):
		refresh(station)
		settle(station)  # the last payment closes a technically closed station (SP-80)
