"""Winch receipts (SP-112): money collected for winch and Jumbo jobs, allocated to the jobs it pays.

Each job keeps what it was agreed at, what has been paid on it, any discount and what is still open,
and its payment status: Open, Partial, Paid or Discounted (also on its booking, W1).

    paid = received on the job (L1) + money received on it later (L1) + winch receipts (here)

A receipt is for one customer. Left without jobs, it is allocated to the customer's oldest open
jobs first; the allocation stays editable. A discount at collection needs a reason, and only the
admin or the Winch Discount Role (Smart Power Settings) gives one.

    Receipt          Dr the receiver's transit / Cr Debtors (the customer); money paid into an
                     official account leaves the transit at once as a pending transfer (A1, SP-117)
    Discount         Dr Winch Discounts (the job's vehicle center) / Cr Debtors (the customer)

A job for a station or one of Smart Power's centers is not collected: it is Open until the admin
confirms it, then Paid. Smart Power Winch Jobs Post (settings) says when it is charged: on the job
day (L1, the default) or when the admin confirms it.

The receivables list, the debt age alert and the old-debt warning on bookings are in receivables.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt, now_datetime

from smart_power.sp_finance.accounts import TRANSIT, holder_account
from smart_power.sp_finance.centers import WINCH, center
from smart_power.sp_winch import field_entry as fe
from smart_power.sp_winch.bookings import BOOKING, FOR_OUTSIDE

RECEIPT, ALLOCATION = "SP Winch Receipt", "SP Receipt Allocation"
OPEN, PARTIAL, PAID, DISCOUNTED = "Open", "Partial", "Paid", "Discounted"
ADMIN = ("SP Admin", "System Manager")
# a change to one of these reverses the receipt's postings and posts it again
MONEY_FIELDS = ("customer", "work_date", "amount", "method", "holder", "to_account", "company")
PENNY = 0.005  # sp-allow-number: half a piastre, rounding


# --- what is open on a job -------------------------------------------------------------------------


def _allocated(job: str, leave_out: str | None = None) -> tuple[float, float]:
	"""What winch receipts have paid on the job, and the discounts they gave."""
	filters = {"job": job, "parenttype": RECEIPT}
	if leave_out:
		filters["parent"] = ("!=", leave_out)
	rows = frappe.get_all(ALLOCATION, filters=filters, fields=["amount", "discount"])
	return sum(flt(r.amount) for r in rows), sum(flt(r.discount) for r in rows)


def job_money(job, leave_out: str | None = None) -> frappe._dict:
	"""agreed, paid, discount and outstanding of a job (a doc or a row with name, agreed_amount
	and received_now). `leave_out`: a receipt whose own allocation is not counted."""
	from_receipts, discount = _allocated(job.get("name"), leave_out)
	paid = flt(job.get("received_now")) + fe._collected_later(job.get("name")) + from_receipts
	agreed = flt(job.get("agreed_amount"))
	return frappe._dict(agreed=agreed, paid=paid, discount=discount, outstanding=agreed - paid - discount)


def payment_status(job, money) -> str:
	if job.get("for_kind") != FOR_OUTSIDE:
		return PAID if money.agreed <= PENNY or job.get("payment_confirmed_at") else OPEN
	if money.outstanding <= PENNY:
		return DISCOUNTED if money.discount > PENNY else PAID
	return PARTIAL if money.paid + money.discount > PENNY else OPEN


def refresh_job(name: str) -> None:
	"""The job's money and status, on the job and its booking, and its review flags."""
	from smart_power.sp_winch import review

	doc = frappe.get_doc(fe.ENTRY, name)
	if doc.entry_kind != fe.JOB:
		return
	money = job_money(doc)
	status = payment_status(doc, money)
	frappe.db.set_value(
		fe.ENTRY,
		name,
		{
			"payment_status": status,
			"paid_amount": money.paid,
			"discount_amount": money.discount,
			"outstanding_amount": max(money.outstanding, 0),
		},
		update_modified=False,
	)
	if doc.booking:
		frappe.db.set_value(BOOKING, doc.booking, "payment_status", status, update_modified=False)
	review.refresh(name)


# --- on the field entry ------------------------------------------------------------------------------


def validate_job(doc) -> None:
	"""A job's agreed amount covers what was collected on it; its customer stays once paid."""
	if doc.entry_kind != fe.JOB or doc.is_new():
		return
	from_receipts, discount = _allocated(doc.name)
	if not (from_receipts or discount):
		return
	settled = flt(doc.received_now) + fe._collected_later(doc.name) + from_receipts + discount
	if settled > flt(doc.agreed_amount) + PENNY:
		frappe.throw(
			_("{0} is already paid or discounted on this job: the agreed amount cannot be less.").format(
				frappe.format(settled, "Currency")
			)
		)
	if doc.has_value_changed("customer_phone") or doc.has_value_changed("for_kind"):
		frappe.throw(_("Winch receipts are allocated to this job: its customer cannot change."))


def on_entry_update(doc) -> None:
	"""A job's own money, or money received on it from the Money tab."""
	if doc.entry_kind == fe.JOB:
		refresh_job(doc.name)
		return
	before = doc.get_doc_before_save()
	for job in {doc.related_job, before and before.related_job}:
		if job:
			refresh_job(job)


# --- the receipt --------------------------------------------------------------------------------------


def may_discount(user: str | None = None) -> bool:
	from smart_power.sp_core.services.settings import get_value

	user = user or frappe.session.user
	role = get_value("winch_discount_role")
	return fe._has_role(ADMIN, user) or bool(role and role in frappe.get_roles(user))


def validate(doc) -> None:
	if doc.is_new():
		doc.recorded_by = frappe.session.user
	doc.holder = doc.holder or frappe.session.user
	if flt(doc.amount) <= 0:
		frappe.throw(_("The amount must be above zero."))
	if fe._code(doc.method) == fe.CASH:
		doc.to_account = None
	else:
		fe._required(doc, {"to_account": "To Account", "photo": "Photo"})
		fe._check_official(doc.to_account)
	if not doc.allocations:
		for row in oldest_first(doc.customer, doc.amount, leave_out=doc.name):
			doc.append("allocations", row)
	# the company of the jobs it pays
	first_job = doc.allocations[0].job if doc.allocations else None
	doc.company = (
		(first_job and frappe.db.get_value(fe.ENTRY, first_job, "company")) or doc.company or _company()
	)
	doc.cost_center = center(WINCH, doc.company)
	_check_rows(doc)
	_check_discount_rights(doc)
	_guard_confirmed(doc)


def _company() -> str | None:
	from erpnext import get_default_company

	return get_default_company() or frappe.db.get_value("Company", {}, "name")


def _check_rows(doc) -> None:
	seen, allocated, discount = set(), 0.0, 0.0
	for row in doc.allocations:
		job = frappe.db.get_value(
			fe.ENTRY,
			row.job,
			[
				"name",
				"entry_kind",
				"for_kind",
				"customer",
				"work_date",
				"vehicle",
				"booking",
				"agreed_amount",
				"received_now",
				"company",
			],
			as_dict=True,
		)
		if not job or job.entry_kind != fe.JOB or job.for_kind != FOR_OUTSIDE:
			frappe.throw(_("Row {0}: {1} is not an outside customer's job.").format(row.idx, row.job))
		if job.customer != doc.customer or job.company != doc.company:
			frappe.throw(_("Row {0}: job {1} is another customer's.").format(row.idx, row.job))
		if row.job in seen:
			frappe.throw(_("Row {0}: job {1} is listed twice.").format(row.idx, row.job))
		seen.add(row.job)
		if flt(row.amount) < 0 or flt(row.discount) < 0:
			frappe.throw(_("Row {0}: the amounts cannot be negative.").format(row.idx))
		if flt(row.amount) + flt(row.discount) <= 0:
			frappe.throw(_("Row {0}: enter an amount or a discount.").format(row.idx))
		still_open = job_money(job, leave_out=doc.name).outstanding
		row.update(
			{
				"work_date": job.work_date,
				"vehicle": job.vehicle,
				"booking": job.booking,
				"open_amount": still_open,
			}
		)
		if flt(row.amount) + flt(row.discount) > still_open + PENNY:
			frappe.throw(
				_("Row {0}: only {1} is open on job {2}.").format(
					row.idx, frappe.format(still_open, "Currency"), row.job
				)
			)
		if flt(row.discount) and not cstr(row.discount_reason).strip():
			frappe.throw(
				_("Row {0}: give the reason for the discount.").format(row.idx), frappe.MandatoryError
			)
		if not flt(row.discount):
			row.discount_reason = None
		allocated += flt(row.amount)
		discount += flt(row.discount)
	if allocated > flt(doc.amount) + PENNY:
		frappe.throw(
			_("The jobs take {0}, more than the receipt's {1}.").format(
				frappe.format(allocated, "Currency"), frappe.format(doc.amount, "Currency")
			)
		)
	doc.allocated_amount, doc.discount_amount = allocated, discount
	doc.unallocated_amount = flt(doc.amount) - allocated


def _discounts(doc) -> list[tuple]:
	return sorted(
		(r.job, flt(r.discount), cstr(r.discount_reason)) for r in doc.allocations if flt(r.discount)
	)


def _check_discount_rights(doc) -> None:
	before = doc.get_doc_before_save()
	if _discounts(doc) == (_discounts(before) if before else []):
		return
	if not may_discount():
		frappe.throw(
			_("Only the admin or the Winch Discount Role gives a discount at collection."),
			frappe.PermissionError,
		)


def _money_changed(doc, before) -> bool:
	return (
		not before
		or any(cstr(before.get(f)) != cstr(doc.get(f)) for f in MONEY_FIELDS)
		or _discounts(before) != _discounts(doc)
	)


def _guard_confirmed(doc) -> None:
	"""Money the admin has confirmed is settled: it is corrected there, not here."""
	if doc.is_new() or not doc.transfer or not _money_changed(doc, doc.get_doc_before_save()):
		return
	if frappe.db.get_value(fe.TRANSFER, doc.transfer, "status") == fe.CONFIRMED:
		frappe.throw(
			_("The admin has confirmed transfer {0}: this money cannot change.").format(doc.transfer)
		)


def on_update(doc) -> None:
	before = doc.get_doc_before_save()
	if _money_changed(doc, before):
		fe._run_as("Administrator", lambda: _repost(doc, bool(before)))
	jobs = {r.job for r in doc.allocations} | ({r.job for r in before.allocations} if before else set())
	for job in jobs:
		refresh_job(job)


def _repost(doc, posted_before: bool) -> None:
	if posted_before:
		fe._reverse(doc)
	remark = _("Winch receipt {0}: {1}").format(doc.name, doc.customer_name or doc.customer)
	transit = holder_account(doc.holder, TRANSIT, doc.company)
	fe._post(
		fe.MONEY_EVENT,
		doc,
		flt(doc.amount),
		company=doc.company,
		posting_date=doc.work_date,
		remark=remark,
		cost_center=doc.cost_center,
		debit_account=transit,
		party_type="Customer",
		party=doc.customer,
	)
	if doc.to_account:
		_hand_in(doc, transit)
	for row in doc.allocations:
		if flt(row.discount):
			fe._post(
				fe.DISCOUNT_EVENT,
				doc,
				flt(row.discount),
				company=doc.company,
				posting_date=doc.work_date,
				remark=_("{0}, job {1}: {2}").format(remark, row.job, row.discount_reason),
				cost_center=frappe.db.get_value(fe.ENTRY, row.job, "cost_center") or doc.cost_center,
				party_type="Customer",
				party=doc.customer,
			)


def _hand_in(doc, transit: str) -> None:
	"""Money paid into an official account: the admin confirms it in A1, as the receiver's transfer."""

	def record() -> str:
		transfer = frappe.get_doc(
			{
				"doctype": fe.TRANSFER,
				"from_account": transit,
				"to_account": doc.to_account,
				"amount": flt(doc.amount),
				"work_date": doc.work_date,
				"reference_no": doc.name,
				"receipt_photo": doc.photo,
			}
		)
		transfer.flags.ignore_permissions = True
		transfer.insert()
		transfer.submit()
		return transfer.name

	doc.db_set("transfer", fe._run_as(doc.holder, record))


def on_trash(doc) -> None:
	if doc.transfer and frappe.db.get_value(fe.TRANSFER, doc.transfer, "status") == fe.CONFIRMED:
		frappe.throw(
			_("The admin has confirmed transfer {0}: this receipt cannot be deleted.").format(doc.transfer)
		)
	fe._run_as("Administrator", lambda: fe._reverse(doc))
	jobs = {r.job for r in doc.allocations}
	frappe.db.delete(ALLOCATION, {"parent": doc.name, "parenttype": RECEIPT})
	for job in jobs:
		refresh_job(job)


# --- allocate --------------------------------------------------------------------------------------------


def oldest_first(customer: str | None, amount: float, leave_out: str | None = None) -> list[dict]:
	"""The customer's open jobs, oldest first, until the amount runs out."""
	if not customer:
		return []
	jobs = frappe.get_all(
		fe.ENTRY,
		filters={"entry_kind": fe.JOB, "for_kind": FOR_OUTSIDE, "customer": customer},
		fields=["name", "agreed_amount", "received_now"],
		order_by="work_date asc, creation asc",
	)
	rows, left = [], flt(amount)
	for job in jobs:
		if left <= PENNY:
			break
		still_open = job_money(job, leave_out).outstanding
		if still_open <= PENNY:
			continue
		take = min(still_open, left)
		rows.append({"job": job.name, "amount": take})
		left -= take
	return rows


@frappe.whitelist()
def suggest(customer: str, amount: float, receipt: str | None = None) -> list[dict]:
	"""For the form's Allocate Oldest First: the rows, with what is open on each job."""
	frappe.has_permission(RECEIPT, "create", throw=True)
	rows = oldest_first(customer, flt(amount), leave_out=receipt)
	for row in rows:
		job = frappe.db.get_value(
			fe.ENTRY,
			row["job"],
			["work_date", "vehicle", "booking", "agreed_amount", "received_now"],
			as_dict=True,
		)
		row.update(
			{
				"work_date": job.work_date,
				"vehicle": job.vehicle,
				"booking": job.booking,
				"open_amount": job_money({**job, "name": row["job"]}, receipt).outstanding,
			}
		)
	return rows


@frappe.whitelist()
def open_jobs_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | str | None = None
) -> list:
	"""The customer's outside jobs with money still open: the jobs a receipt can pay."""
	frappe.has_permission(RECEIPT, "create", throw=True)
	filters = frappe.parse_json(filters) or {}
	return frappe.get_all(
		fe.ENTRY,
		filters={
			"entry_kind": fe.JOB,
			"for_kind": FOR_OUTSIDE,
			"customer": filters.get("customer") or "",
			"payment_status": ("in", (OPEN, PARTIAL)),
			"name": ("like", f"%{txt}%"),
		},
		fields=["name", "work_date", "outstanding_amount"],
		order_by="work_date asc",
		as_list=True,
		start=start,
		page_length=page_len,
	)


# --- Smart Power's own jobs -------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def confirm_jobs(names: str | list) -> int:
	"""The admin closes jobs for stations and centers; charged now if they post on confirmation."""
	if not fe._has_role(ADMIN):
		frappe.throw(_("Only the admin confirms Smart Power's own jobs."), frappe.PermissionError)
	names = frappe.parse_json(names) if isinstance(names, str) else names
	done = 0
	for name in names or []:
		doc = frappe.get_doc(fe.ENTRY, name)
		if doc.entry_kind != fe.JOB or doc.for_kind == FOR_OUTSIDE:
			frappe.throw(_("{0} is not a job for a station or one of our centers.").format(name))
		if doc.payment_confirmed_at:
			continue
		deferred = fe.deferred(doc)
		doc.db_set({"payment_confirmed_by": frappe.session.user, "payment_confirmed_at": now_datetime()})
		if deferred and not fe.postings(doc):
			fe._run_as("Administrator", lambda doc=doc: fe._post_job(doc))
		refresh_job(name)
		done += 1
	return done
