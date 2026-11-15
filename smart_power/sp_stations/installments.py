"""Instalment tracking (SP-81, CL1).

The instalments are the contract's payment schedule (the Sales Order's Payment Schedule rows,
ERD 7.1). The station's covered money (confirmed payments and write-offs) is allocated to them
first in, first out:

    sp_paid_amount   what is allocated to the row
    sp_status        Paid (covered) · Overdue (due date passed, not covered) · Due

allocate(station) runs whenever the station's money is refreshed (a payment confirmed, reversed
or written off) and in the daily job, which also sends the alerts once per instalment:
- due within `Instalment Due Alert` days → the collection owner;
- overdue → the collection owner and the admin.
Apps can listen through the `sp_installment_events` hook: fn(event, station, row), with event
"installment_due" or "installment_overdue" (Automations X9 builds on it).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today

STATION, SO, ROW = "SP Station", "Sales Order", "Payment Schedule"
DUE, OVERDUE, PAID = "Due", "Overdue", "Paid"
OPEN_STATUSES = ("Open", "Purchasing", "Installing", "Technically closed")
ADMIN_ROLE = "SP Admin"
ROUNDING = 0.005  # sp-allow-number: half a piastre


def schedule_rows(doc) -> list:
	"""The contract's instalments, oldest first (none before the contract exists)."""
	if not doc.sales_order:
		return []
	return frappe.get_all(
		ROW,
		{"parent": doc.sales_order, "parenttype": SO},
		[
			"name",
			"due_date",
			"payment_amount",
			"sp_paid_amount",
			"sp_status",
			"sp_due_alerted",
			"sp_overdue_alerted",
		],
		order_by="due_date asc, idx asc",
	)


def allocation(doc, rows: list | None = None, on: str | None = None) -> list[dict]:
	"""Each instalment with what the covered money pays of it and its status (nothing saved)."""
	rows = schedule_rows(doc) if rows is None else rows
	left = flt(doc.paid_amount) + flt(doc.write_off_amount)
	day = getdate(on or today())
	result = []
	for row in rows:
		amount = flt(row.payment_amount)
		paid = min(amount, max(left, 0.0))
		left -= paid
		if paid >= amount - ROUNDING:
			status = PAID
		elif row.due_date and getdate(row.due_date) < day:
			status = OVERDUE
		else:
			status = DUE
		result.append({**row, "paid": paid, "left": max(amount - paid, 0.0), "status": status})
	return result


def overdue_of(rows: list[dict]) -> tuple[float, int]:
	"""The overdue amount and the days since the oldest overdue instalment fell due."""
	late = [r for r in rows if r["status"] == OVERDUE]
	if not late:
		return 0.0, 0
	oldest = min(getdate(r["due_date"]) for r in late)
	return sum(r["left"] for r in late), (getdate(today()) - oldest).days


def allocate(station) -> list[dict]:
	"""Store each instalment's allocation and status, and the station's overdue."""
	doc = frappe.get_doc(STATION, station) if isinstance(station, str) else station
	rows = allocation(doc)
	for row in rows:
		if flt(row["sp_paid_amount"]) != row["paid"] or row["sp_status"] != row["status"]:
			values = {"sp_paid_amount": row["paid"], "sp_status": row["status"]}
			if row["status"] == PAID:
				# paid: a later bounce or reversal alerts again
				values.update(sp_due_alerted=0, sp_overdue_alerted=0)
			frappe.db.set_value(ROW, row["name"], values, update_modified=False)
	amount, _days = overdue_of(rows)
	frappe.db.set_value(
		STATION, doc.name, {"overdue_amount": amount, "has_overdue": int(amount > 0)}, update_modified=False
	)
	return rows


# --- the daily job -------------------------------------------------------------------------------


def update_installments() -> dict:
	"""Daily: every open station with a contract is allocated; due and overdue alerts go once."""
	from smart_power.sp_core.services.settings import get_value

	lead = cint(get_value("installment_due_lead_days"))
	horizon = getdate(add_days(today(), lead))
	sent = {"installment_due": 0, "installment_overdue": 0}
	for name in frappe.get_all(
		STATION, {"status": ("in", OPEN_STATUSES), "sales_order": ("is", "set")}, pluck="name"
	):
		doc = frappe.get_doc(STATION, name)
		for row in allocate(doc):
			if row["status"] == OVERDUE and not cint(row["sp_overdue_alerted"]):
				_alert(doc, row, "installment_overdue", [doc.collection_owner, *_admins()])
				frappe.db.set_value(ROW, row["name"], "sp_overdue_alerted", 1, update_modified=False)
				sent["installment_overdue"] += 1
			elif (
				row["status"] == DUE
				and row["due_date"]
				and getdate(row["due_date"]) <= horizon
				and not cint(row["sp_due_alerted"])
			):
				_alert(doc, row, "installment_due", [doc.collection_owner])
				frappe.db.set_value(ROW, row["name"], "sp_due_alerted", 1, update_modified=False)
				sent["installment_due"] += 1
	return sent


def _admins() -> list[str]:
	from smart_power.sp_sales.quote_request import _users_with

	return _users_with(ADMIN_ROLE)


def _alert(doc, row: dict, event: str, users: list) -> None:
	from frappe.desk.doctype.notification_log.notification_log import make_notification_logs

	customer = doc.customer_name or doc.customer
	left = frappe.format(row["left"], "Currency")
	when = frappe.format(getdate(row["due_date"]), "Date")
	if event == "installment_overdue":
		subject = _("Overdue: {0} of {1} (station {2}) was due on {3}").format(left, customer, doc.name, when)
	else:
		subject = _("Instalment due: {0} from {1} (station {2}) on {3}").format(
			left, customer, doc.name, when
		)
	users = sorted({u for u in users if u})
	if users:
		make_notification_logs(
			frappe._dict(
				{
					"type": "Alert",
					"document_type": STATION,
					"document_name": doc.name,
					"subject": subject,
					"from_user": "Administrator",
				}
			),
			users,
		)
	for fn in frappe.get_hooks("sp_installment_events"):
		frappe.get_attr(fn)(event, doc, row)
