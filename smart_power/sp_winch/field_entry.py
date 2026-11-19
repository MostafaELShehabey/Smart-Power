"""Light field entry (SP-108, L1): one record for a job, an expense or money, logged after the work.

The date and the center fill themselves (the vehicle's center) and the real entry time is kept.
Saving posts through the Account Map; changing the money on an entry reverses and posts it again.

    Station job      Dr Winch Services (Projects, the station's project) / Cr vehicle income, internal
    Center job       Dr Winch Services (the requesting center) / Cr vehicle income, internal
    Outside job      Dr Debtors (the customer) / Cr vehicle income
    Received         Dr the operator's transit / Cr Debtors
    Expense          Dr Vehicle Running Costs (the vehicle's center) / Cr custody or the shop cash
    Deposit          a pending SP Transfer from the operator's transit: the admin confirms it (SP-117)

Money received by a method other than cash reaches the operator's transit and leaves it at once as
a pending transfer to the account it went to, so nothing lands on an official account unconfirmed.
The phone pages are SP-180, the 3-day lock SP-109 and the review flags SP-110.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from smart_power.sp_finance.accounts import CUSTODY, OFFICIAL, TRANSIT, holder_account
from smart_power.sp_finance.centers import PROJECTS, center
from smart_power.sp_finance.journal import allow_cancel
from smart_power.sp_finance.posting import post, postings
from smart_power.sp_winch.bookings import (
	BOOKED,
	BOOKING,
	CANCELLED,
	DONE,
	FOR_CENTER,
	FOR_OUTSIDE,
	FOR_STATION,
)
from smart_power.sp_winch.vehicles import JUMBO_TYPE, VEHICLE, record_odometer

ENTRY, LIST_VALUE, TRANSFER, JE = "SP Field Entry", "SP List Value", "SP Transfer", "Journal Entry"
JOB, EXPENSE, MONEY = "Job", "Expense", "Money"
RECEIVED, DEPOSIT = "Received", "Deposit"
FROM_CUSTODY, SHOP_CASH = "Custody", "Shop cash"
CASH, OIL, WORKER_WAGE = "CASH", "OIL", "WORKER_WAGE"
PENDING, CONFIRMED = "Pending", "Confirmed"
INTERNAL_EVENT, JOB_EVENT, EXPENSE_EVENT, MONEY_EVENT = (
	"Winch Internal Charge",
	"Field Job",
	"Field Expense",
	"Field Money",
)
SERVICES_ACCOUNT, RUNNING_ACCOUNT, WINCH_INCOME, JUMBO_INCOME, SHOP_ACCOUNT = (
	"Winch Services",
	"Vehicle Running Costs",
	"Winch Income",
	"Jumbo Income",
	"Showroom Safe",
)
SEES_ALL = ("System Manager", "SP Admin", "SP Winch Manager", "SP Winch Reviewer", "SP Project Manager")
LOGS_FOR_OTHERS = ("System Manager", "SP Admin", "SP Winch Manager", "SP Winch Reviewer")

JOB_FIELDS = (
	"booking",
	"job_type",
	"for_kind",
	"station",
	"internal_center",
	"customer_name",
	"customer_phone",
	"customer",
	"place",
	"hp",
	"depth",
	"days",
	"hours",
	"km",
	"agreed_amount",
	"received_now",
)
EXPENSE_FIELDS = ("expense_type", "paid_from", "odometer", "worker")
MONEY_FIELDS = ("money_kind", "related_job")
SHARED_FIELDS = {"amount": (EXPENSE, MONEY), "received_method": (JOB, MONEY), "to_account": (JOB, MONEY)}
BOOKED_FOR = ("for_kind", "station", "internal_center", "customer_name", "customer_phone")
FROM_BOOKING = ("vehicle", "job_type", "place", "agreed_amount")
# a change to one of these reverses the entry's postings and posts it again
MONEY_FIELDS_POSTED = (
	"entry_kind",
	"vehicle",
	"work_date",
	"on_behalf_of",
	"for_kind",
	"station",
	"internal_center",
	"customer_name",
	"customer_phone",
	"agreed_amount",
	"received_now",
	"received_method",
	"to_account",
	"expense_type",
	"amount",
	"paid_from",
	"money_kind",
	"related_job",
)
# what a phone or the desk may send; the rest is the system's
ENTERED_FIELDS = (
	"entry_kind",
	"vehicle",
	"work_date",
	"on_behalf_of",
	*JOB_FIELDS,
	*EXPENSE_FIELDS,
	*MONEY_FIELDS,
	*SHARED_FIELDS,
	"photo",
	"voice_note",
	"note",
	"device_time",
	"client_uuid",
)


def _required(doc, fields: dict) -> None:
	for fieldname, label in fields.items():
		if not doc.get(fieldname):
			frappe.throw(_("Enter the {0}.").format(_(label)), frappe.MandatoryError)


def _code(value: str | None) -> str | None:
	return frappe.db.get_value(LIST_VALUE, value, "code") if value else None


def _has_role(roles: tuple, user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(roles) & set(frappe.get_roles(user)))


def _holder(doc) -> str:
	"""Whose cash and custody the entry moves: the operator, whoever typed it."""
	return doc.on_behalf_of or doc.logged_by


# --- validate -----------------------------------------------------------------------------------


def validate(doc) -> None:
	_set_people(doc)
	_from_booking(doc)
	_set_vehicle(doc)
	_keep_only_its_kind(doc)
	{JOB: _validate_job, EXPENSE: _validate_expense, MONEY: _validate_money}[doc.entry_kind](doc)
	_guard_confirmed(doc)


def _set_people(doc) -> None:
	if doc.is_new():
		doc.logged_by = frappe.session.user
		doc.status = doc.status or "Logged"
		if doc.device_time:
			doc.sync_time = now_datetime()
	if doc.on_behalf_of and doc.on_behalf_of != doc.logged_by and not _has_role(LOGS_FOR_OTHERS):
		frappe.throw(_("Only the winch manager logs an entry for someone else."), frappe.PermissionError)


def _from_booking(doc) -> None:
	"""A booked job is for whoever it was booked for; the rest opens as planned and can be changed."""
	if doc.entry_kind != JOB or not doc.booking:
		return
	booking = frappe.get_doc(BOOKING, doc.booking)
	if booking.status == CANCELLED:
		frappe.throw(_("Booking {0} was cancelled.").format(doc.booking))
	logged = frappe.db.get_value(ENTRY, {"booking": doc.booking, "name": ("!=", doc.name or "")})
	if logged:
		frappe.throw(_("Booking {0} is already logged on {1}.").format(doc.booking, logged))
	doc.update({fieldname: booking.get(fieldname) for fieldname in BOOKED_FOR})
	for fieldname in FROM_BOOKING:
		if not doc.get(fieldname):
			doc.set(fieldname, booking.get(fieldname))


def _set_vehicle(doc) -> None:
	_required(doc, {"vehicle": "Vehicle"})
	row = frappe.db.get_value(VEHICLE, doc.vehicle, ["sp_cost_center", "company"], as_dict=True)
	doc.cost_center, doc.company = row.sp_cost_center, row.company


def _keep_only_its_kind(doc) -> None:
	"""A kind changed on the form leaves nothing of the old kind behind."""
	own = {JOB: JOB_FIELDS, EXPENSE: EXPENSE_FIELDS, MONEY: MONEY_FIELDS}
	for kind, fields in own.items():
		if kind != doc.entry_kind:
			doc.update(dict.fromkeys(fields))
	for fieldname, kinds in SHARED_FIELDS.items():
		if doc.entry_kind not in kinds:
			doc.set(fieldname, None)


def _validate_receipt(doc, amount: float) -> None:
	"""Cash stays with the operator; any other method names the account the money went to."""
	if amount <= 0:
		doc.received_method = doc.to_account = None
		return
	_required(doc, {"received_method": "Received Method"})
	if _code(doc.received_method) == CASH:
		doc.to_account = None
		return
	_required(doc, {"to_account": "To Account", "photo": "Photo"})
	_check_official(doc.to_account)


def _check_official(account: str) -> None:
	if frappe.db.get_value("Account", account, "sp_account_kind") != OFFICIAL:
		frappe.throw(_("{0} is not an official account.").format(frappe.bold(account)))


def _validate_job(doc) -> None:
	_required(doc, {"job_type": "Job Type", "for_kind": "For"})
	if flt(doc.agreed_amount) < 0 or flt(doc.received_now) < 0:
		frappe.throw(_("The amounts cannot be negative."))
	if doc.for_kind == FOR_STATION:
		_required(doc, {"station": "Station"})
		if flt(doc.agreed_amount) and not frappe.db.get_value("SP Station", doc.station, "project"):
			frappe.throw(_("Station {0} has no project to charge.").format(doc.station))
	elif doc.for_kind == FOR_OUTSIDE:
		_required(doc, {"customer_name": "Customer Name", "customer_phone": "Customer Phone"})
	else:
		_required(doc, {"internal_center": "Requesting Center"})
	if doc.for_kind != FOR_OUTSIDE:
		doc.received_now = 0
		doc.customer = None
	_validate_receipt(doc, flt(doc.received_now))
	collected = flt(doc.received_now) + _collected_later(doc.name)
	if collected > flt(doc.agreed_amount):
		frappe.throw(
			_("Received {0} is more than the agreed {1}.").format(
				frappe.format(collected, "Currency"), frappe.format(doc.agreed_amount, "Currency")
			)
		)
	if _collected_later(doc.name) and doc.has_value_changed("customer_phone"):
		frappe.throw(_("Money was already received on this job: its customer cannot change."))


def _validate_expense(doc) -> None:
	_required(doc, {"expense_type": "Expense Type", "paid_from": "Paid From"})
	if flt(doc.amount) <= 0:
		frappe.throw(_("The amount must be above zero."))
	code = _code(doc.expense_type)
	if code == OIL:
		_required(doc, {"odometer": "Odometer"})
	if code == WORKER_WAGE:
		_required(doc, {"worker": "Worker"})


def _collected_later(job: str | None, leave_out: str | None = None) -> float:
	"""What the Money tab has received on this job since it was logged."""
	if not job:
		return 0.0
	filters = {"related_job": job, "entry_kind": MONEY, "money_kind": RECEIVED}
	if leave_out:
		filters["name"] = ("!=", leave_out)
	return sum(flt(a) for a in frappe.get_all(ENTRY, filters=filters, pluck="amount"))


def _validate_money(doc) -> None:
	_required(doc, {"money_kind": "Money Kind"})
	if flt(doc.amount) <= 0:
		frappe.throw(_("The amount must be above zero."))
	if doc.money_kind == DEPOSIT:
		_required(doc, {"to_account": "To Account", "photo": "Photo"})
		_check_official(doc.to_account)
		doc.related_job = doc.received_method = None
		return
	_required(doc, {"related_job": "Related Job"})
	job = frappe.db.get_value(
		ENTRY, doc.related_job, ["entry_kind", "for_kind", "agreed_amount", "received_now"], as_dict=True
	)
	if not job or job.entry_kind != JOB or job.for_kind != FOR_OUTSIDE:
		frappe.throw(_("Money is received on an outside customer's job."))
	still_open = flt(job.agreed_amount) - flt(job.received_now) - _collected_later(doc.related_job, doc.name)
	if flt(doc.amount) > still_open:
		frappe.throw(_("Only {0} is still open on this job.").format(frappe.format(still_open, "Currency")))
	_validate_receipt(doc, flt(doc.amount))


def _money_changed(doc) -> bool:
	before = doc.get_doc_before_save()
	return not before or any(before.get(f) != doc.get(f) for f in MONEY_FIELDS_POSTED)


def _guard_confirmed(doc) -> None:
	"""Money the admin has confirmed is settled: it is corrected there, not here."""
	if doc.is_new() or not doc.transfer or not _money_changed(doc):
		return
	if frappe.db.get_value(TRANSFER, doc.transfer, "status") == CONFIRMED:
		frappe.throw(
			_("The admin has confirmed transfer {0}: this money cannot change.").format(doc.transfer)
		)


# --- post ---------------------------------------------------------------------------------------


def _run_as(user: str, action):
	"""ERPNext checks accounts against the session user, and an operator may not read them. The
	entry's own rules have already decided what this person may do."""
	current = frappe.session.user
	frappe.set_user(user)  # nosemgrep
	try:
		return action()
	finally:
		frappe.set_user(current)  # nosemgrep


def on_update(doc) -> None:
	before = doc.get_doc_before_save()
	if _money_changed(doc):
		_run_as("Administrator", lambda: _repost(doc, bool(before)))
	_follow_booking(doc, before)
	if doc.odometer and (not before or before.odometer != doc.odometer):
		_run_as("Administrator", lambda: _read_odometer(doc))


def _repost(doc, posted_before: bool) -> None:
	if posted_before:
		_reverse(doc)
	{JOB: _post_job, EXPENSE: _post_expense, MONEY: _post_money}[doc.entry_kind](doc)
	for entry in postings(doc):
		frappe.db.set_value(
			JE, entry, {"owner": doc.logged_by, "modified_by": doc.logged_by}, update_modified=False
		)


def _reverse(doc) -> None:
	for name in postings(doc):
		entry = frappe.get_doc(JE, name)
		allow_cancel(entry)
		entry.cancel()
	if doc.transfer and frappe.db.get_value(TRANSFER, doc.transfer, "status") == PENDING:
		transfer = frappe.get_doc(TRANSFER, doc.transfer)
		transfer.flags.ignore_permissions = True
		transfer.cancel()
	if doc.transfer:
		doc.db_set("transfer", None)


def _income_account(doc) -> str | None:
	"""The Jumbo car earns on its own account; every other vehicle follows the Account Map."""
	if frappe.db.get_value(VEHICLE, doc.vehicle, "sp_vehicle_type") != JUMBO_TYPE:
		return None
	return _account(doc.company, JUMBO_INCOME)


def _account(company: str, account_name: str) -> str | None:
	return frappe.db.get_value("Account", {"company": company, "account_name": account_name, "is_group": 0})


def _remark(doc) -> str:
	who = doc.customer_name or doc.station or doc.internal_center or ""
	return _("Field entry {0}: {1}").format(doc.name, who)


def _post_job(doc) -> None:
	amount = flt(doc.agreed_amount)
	if doc.for_kind == FOR_OUTSIDE:
		_set_customer(doc)
	if amount <= 0:
		return
	common = {
		"company": doc.company,
		"posting_date": doc.work_date,
		"remark": _remark(doc),
		"credit_account": _income_account(doc),
		"credit_center": doc.cost_center,
	}
	if doc.for_kind == FOR_OUTSIDE:
		post(
			JOB_EVENT,
			doc,
			amount,
			debit_center=doc.cost_center,
			party_type="Customer",
			party=doc.customer,
			**common,
		)
		_receive(doc, flt(doc.received_now), doc.customer)
	elif doc.for_kind == FOR_STATION:
		project = frappe.db.get_value("SP Station", doc.station, "project")
		post(
			INTERNAL_EVENT,
			doc,
			amount,
			project=project,
			debit_center=center(PROJECTS, doc.company),
			internal_charge=True,
			**common,
		)
	elif doc.for_kind == FOR_CENTER:
		post(INTERNAL_EVENT, doc, amount, debit_center=doc.internal_center, internal_charge=True, **common)


def _set_customer(doc) -> None:
	"""The outside customer is found by mobile, or added, so the debt follows the person."""
	from smart_power.sp_sales.customer import normalize_mobile

	mobile = normalize_mobile(doc.customer_phone)
	found = frappe.db.get_value("Customer", {"sp_mobile": mobile})
	if not found:
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": doc.customer_name, "sp_mobile": mobile}
		)
		customer.flags.ignore_permissions = True
		found = customer.insert().name
	doc.db_set("customer", found)


def _receive(doc, amount: float, customer: str | None) -> None:
	if amount <= 0:
		return
	transit = holder_account(_holder(doc), TRANSIT, doc.company)
	post(
		MONEY_EVENT,
		doc,
		amount,
		company=doc.company,
		posting_date=doc.work_date,
		remark=_remark(doc),
		cost_center=doc.cost_center,
		debit_account=transit,
		party_type="Customer",
		party=customer,
	)
	if doc.to_account:
		_deposit(doc, amount, transit)


def _deposit(doc, amount: float, transit: str) -> None:
	"""The admin confirms it in A1; the transfer belongs to the operator who holds the money."""

	def record() -> str:
		transfer = frappe.get_doc(
			{
				"doctype": TRANSFER,
				"from_account": transit,
				"to_account": doc.to_account,
				"amount": amount,
				"work_date": doc.work_date,
				"reference_no": doc.name,
				"receipt_photo": doc.photo,
			}
		)
		transfer.flags.ignore_permissions = True
		transfer.insert()
		transfer.submit()
		return transfer.name

	doc.db_set("transfer", _run_as(_holder(doc), record))


def _post_expense(doc) -> None:
	custody = doc.paid_from == FROM_CUSTODY
	post(
		EXPENSE_EVENT,
		doc,
		flt(doc.amount),
		company=doc.company,
		posting_date=doc.work_date,
		remark=_remark(doc),
		cost_center=doc.cost_center,
		credit_account=holder_account(_holder(doc), CUSTODY, doc.company) if custody else None,
	)


def _post_money(doc) -> None:
	if doc.money_kind == DEPOSIT:
		_deposit(doc, flt(doc.amount), holder_account(_holder(doc), TRANSIT, doc.company))
		return
	_receive(doc, flt(doc.amount), frappe.db.get_value(ENTRY, doc.related_job, "customer"))


def _follow_booking(doc, before) -> None:
	"""A logged job finishes its booking; moved to another booking, the first one opens again."""
	if before and before.booking and before.booking != doc.booking:
		frappe.db.set_value(BOOKING, before.booking, "status", BOOKED)
	if doc.booking:
		frappe.db.set_value(BOOKING, doc.booking, "status", DONE)


def _read_odometer(doc) -> None:
	"""A late entry can carry an older reading: it stays on the entry and moves nothing back."""
	if cint(doc.odometer) >= cint(frappe.db.get_value(VEHICLE, doc.vehicle, "sp_odometer_km")):
		record_odometer(doc.vehicle, cint(doc.odometer), oil_changed=_code(doc.expense_type) == OIL)


# --- save from a phone or the desk ----------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def save_entry(values: str | dict) -> str:
	"""Log an entry. The same client_uuid sent twice gives the one entry already logged."""
	values = frappe.parse_json(values)
	uuid = values.get("client_uuid")
	existing = uuid and frappe.db.get_value(ENTRY, {"client_uuid": uuid})
	if existing:
		return existing
	doc = frappe.get_doc({"doctype": ENTRY, **{k: values[k] for k in ENTERED_FIELDS if k in values}})
	frappe.db.savepoint("sp_field_entry")
	try:
		doc.insert()
	except frappe.UniqueValidationError:  # the second of two at the same moment
		frappe.db.rollback(save_point="sp_field_entry")
		frappe.clear_messages()
		return frappe.db.get_value(ENTRY, {"client_uuid": uuid})
	return doc.name


# --- who sees what --------------------------------------------------------------------------------


def query_conditions(user: str | None = None) -> str:
	"""An operator sees their own entries; the office sees all of them."""
	user = user or frappe.session.user
	if _has_role(SEES_ALL, user):
		return ""
	u = frappe.db.escape(user)
	return f"(`tabSP Field Entry`.logged_by = {u} or `tabSP Field Entry`.on_behalf_of = {u})"


def has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	return _has_role(SEES_ALL, user) or doc.is_new() or user in (doc.logged_by, doc.on_behalf_of)


# --- the Account Map ------------------------------------------------------------------------------


def seed_account_map(company: str) -> None:
	"""The field entry rows of the Account Map, once. The admin can change any of them."""
	from smart_power.constants import SETTINGS_DOCTYPE

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	have = {r.event for r in settings.account_map}
	default = frappe.get_cached_value("Company", company, "cost_center")
	debtors = frappe.get_cached_value("Company", company, "default_receivable_account")
	services, running, income, shop = (
		_account(company, n) for n in (SERVICES_ACCOUNT, RUNNING_ACCOUNT, WINCH_INCOME, SHOP_ACCOUNT)
	)
	rows = (
		(INTERNAL_EVENT, services, income, "Debit side", "A job for a station or a center: nets to zero."),
		(JOB_EVENT, debtors, income, "None", "A job for an outside customer."),
		(EXPENSE_EVENT, running, shop, "None", "The credit is the operator's custody when paid from it."),
		(MONEY_EVENT, shop, debtors, "None", "The debit is the operator's own transit account."),
	)
	for event, debit, credit, project_rule, note in rows:
		if event in have or not (debit and credit and default):
			continue
		settings.append(
			"account_map",
			{
				"event": event,
				"debit_account": debit,
				"debit_center_rule": "From document",
				"debit_cost_center": default,
				"credit_account": credit,
				"credit_center_rule": "From document",
				"credit_cost_center": default,
				"project_rule": project_rule,
				"note": note,
			},
		)
	settings.flags.ignore_permissions = True
	settings.save()
