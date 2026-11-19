"""Winch receivables (SP-112): who owes for winch and Jumbo jobs, since when, and what was said.

    receivables()            one row per customer with jobs still open: phone, jobs, what is open,
                             the oldest job's age and the last follow-up note
    add_note(customer, note) a follow-up note, kept on the customer
    to_confirm()             Smart Power's own jobs waiting for the admin's confirmation
    check_old_debts()        daily: a job unpaid past Winch Debt Age Alert (months) notifies the
                             winch manager and the admin, once
    old_debt_of_phone(phone) what the rule winch_old_debt warns about on a new booking

The page is sp-winch-receivables. Receipts and the payment status are in receipts.
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, date_diff, flt, getdate, nowdate

from smart_power.notify import send
from smart_power.sp_winch.bookings import FOR_OUTSIDE
from smart_power.sp_winch.field_entry import ENTRY, JOB, _has_role
from smart_power.sp_winch.receipts import OPEN, PARTIAL, RECEIPT

READERS = ("SP Winch Manager", "SP Project Manager", "SP Winch Reviewer", "SP Admin", "System Manager")
ALERTED_ROLES = ("SP Winch Manager", "SP Admin")
EVENT_OLD_DEBT = "winch_old_debt"
DAYS_IN_MONTH = 30  # sp-allow-number: the age shown in months, roughly
NOTES_SHOWN = 1  # sp-allow-number: the last follow-up note on the list


def _check_reader() -> None:
	if not _has_role(READERS):
		frappe.throw(_("Only the winch office sees the winch receivables."), frappe.PermissionError)


def debt_age_months() -> int:
	from smart_power.sp_core.services.settings import get_value

	return cint(get_value("winch_debt_age_months"))


def _open_jobs(filters: dict | None = None) -> list:
	return frappe.get_all(
		ENTRY,
		filters={
			"entry_kind": JOB,
			"for_kind": FOR_OUTSIDE,
			"payment_status": ("in", (OPEN, PARTIAL)),
			**(filters or {}),
		},
		fields=[
			"name",
			"customer",
			"customer_name",
			"customer_phone",
			"vehicle",
			"work_date",
			"agreed_amount",
			"paid_amount",
			"outstanding_amount",
			"payment_status",
			"debt_alerted",
		],
		order_by="work_date asc, creation asc",
	)


def _last_note(customer: str) -> dict | None:
	rows = frappe.get_all(
		"Comment",
		filters={"reference_doctype": "Customer", "reference_name": customer, "comment_type": "Comment"},
		fields=["content", "owner", "creation"],
		order_by="creation desc",
		limit=NOTES_SHOWN,
	)
	if not rows:
		return None
	row = rows[0]
	return {
		"note": frappe.utils.strip_html(row.content or ""),
		"by": frappe.utils.get_fullname(row.owner),
		"on": row.creation,
	}


@frappe.whitelist()
def receivables() -> dict:
	"""Customers with winch jobs still open, the oldest debt first."""
	_check_reader()
	months, today = debt_age_months(), getdate(nowdate())
	by_customer: dict = {}
	for job in _open_jobs():
		row = by_customer.setdefault(
			job.customer,
			{
				"customer": job.customer,
				"customer_name": job.customer_name,
				"phone": frappe.db.get_value("Customer", job.customer, "sp_mobile") or job.customer_phone,
				"jobs": [],
				"outstanding": 0.0,
				"oldest": job.work_date,
			},
		)
		row["jobs"].append(
			{
				"name": job.name,
				"vehicle": job.vehicle,
				"work_date": job.work_date,
				"agreed": flt(job.agreed_amount),
				"paid": flt(job.paid_amount),
				"outstanding": flt(job.outstanding_amount),
				"status": job.payment_status,
			}
		)
		row["outstanding"] += flt(job.outstanding_amount)
	rows = []
	for row in by_customer.values():
		days = date_diff(today, row["oldest"])
		old = bool(months) and getdate(row["oldest"]) < getdate(add_months(today, -months))
		rows.append(
			{
				**row,
				"age_days": days,
				"age_months": days // DAYS_IN_MONTH,
				"old": old,
				"last_note": _last_note(row["customer"]),
			}
		)
	rows.sort(key=lambda r: (r["oldest"], r["customer_name"] or ""))
	return {
		"customers": rows,
		"total": sum(r["outstanding"] for r in rows),
		"debt_age_months": months,
		"can_record": frappe.has_permission(RECEIPT, "create"),
		"can_confirm": _has_role(("SP Admin", "System Manager")),
	}


@frappe.whitelist(methods=["POST"])
def add_note(customer: str, note: str) -> str:
	"""A follow-up note on the customer: who said what about paying."""
	_check_reader()
	note = (note or "").strip()
	if not note:
		frappe.throw(_("Write the note first."), frappe.MandatoryError)
	comment = frappe.get_doc("Customer", customer).add_comment("Comment", note)
	return comment.name


@frappe.whitelist()
def to_confirm() -> list[dict]:
	"""Jobs for stations and our own centers, still waiting for the admin's confirmation."""
	_check_reader()
	rows = frappe.get_all(
		ENTRY,
		filters={"entry_kind": JOB, "for_kind": ("!=", FOR_OUTSIDE), "payment_status": OPEN},
		fields=["name", "vehicle", "work_date", "for_kind", "station", "internal_center", "agreed_amount"],
		order_by="work_date asc, creation asc",
	)
	return [{**r, "for": r.station or r.internal_center, "agreed": flt(r.agreed_amount)} for r in rows]


# --- old debt --------------------------------------------------------------------------------------


def _old_jobs(filters: dict | None = None) -> list:
	months = debt_age_months()
	if not months:
		return []
	cutoff = add_months(nowdate(), -months)
	return _open_jobs({"work_date": ("<", cutoff), **(filters or {})})


def check_old_debts() -> list[str]:
	"""Daily: each job unpaid past the debt age is announced once to the winch manager and the admin."""
	from smart_power.sp_sales.quote_request import _users_with

	jobs = [j for j in _old_jobs() if not j.debt_alerted]
	if not jobs:
		return []
	users = sorted({u for role in ALERTED_ROLES for u in _users_with(role)})
	for job in jobs:
		send(
			EVENT_OLD_DEBT,
			users,
			ENTRY,
			job.name,
			_("Old winch debt: {0} owes {1} since {2}").format(
				job.customer_name,
				frappe.format(job.outstanding_amount, "Currency"),
				frappe.format(job.work_date, "Date"),
			),
			from_user="Administrator",
		)
		frappe.db.set_value(ENTRY, job.name, "debt_alerted", 1, update_modified=False)
	return [j.name for j in jobs]


def old_debt_of_phone(phone: str | None):
	"""The customer with this phone, when their jobs are unpaid past the debt age."""
	from smart_power.sp_sales.customer import normalize_mobile

	if not phone:
		return None
	customer = frappe.db.get_value(
		"Customer", {"sp_mobile": normalize_mobile(phone)}, ["name", "customer_name"], as_dict=True
	)
	if not customer:
		return None
	jobs = _old_jobs({"customer": customer.name})
	if not jobs:
		return None
	return frappe._dict(
		customer=customer.name,
		customer_name=customer.customer_name,
		outstanding=sum(flt(j.outstanding_amount) for j in jobs),
		oldest=jobs[0].work_date,
	)
