"""SH2 Showroom cash box (SP-104; decision 63; ERD 7.4 CashBoxDay; notes 6-11 and 8-11-2026).

One day of the showroom box (خزنة المعرض, a transit account) at a time:

    opening                 the last closing counted (confirmed, or waiting for the admin)
    + sales in              cash sales into the box (SP-102's showroom sales)
    + station payments in   station payments taken at the showroom, pending and confirmed (SH5)
    - expenses out          SP Expense paid from the shop cash (SP-123)
    - deposits out          SP Transfer out of the box to the Post or the bank (SH3), pending and
                            confirmed
    = expected closing

A deposit waiting for the admin (SP-105) is "deposit pending": out of the box's cash in hand, not
yet in the bank. The day shows it as its own line until it is confirmed, whatever its date.

The cashier closes the day with the counted cash; a difference needs a reason. The close waits
for the admin in the confirmations centre (A1); confirming posts the difference (Account Map
event "Cash Over/Short", the Showroom center): short, Dr Cash Over and Short / Cr the box; over,
the other way. Rejected, the day is open again with the admin's reason.

Cash held too long (decision 63, owner 2026-11-21): the box warns when its cash is over the
amount limit (Showroom Box Cash Limit, 100,000) or its oldest cash has waited longer than the
days limit (Cash Held Limit, or the box account's own Max Days Held). The rule
showroom_cash_over_limit is Warn by default; at Block, the day cannot be closed until a deposit
is recorded. The page shows a red banner with the days held.
"""

import frappe
from frappe import _
from frappe.utils import flt, today

from smart_power.sp_core.inbox import close_tasks, create_task
from smart_power.sp_core.services.audit import audited

DAY, PAYMENT, EXPENSE, TRANSFER = "SP Cash Box Day", "SP Customer Payment", "SP Expense", "SP Transfer"
OPEN, PENDING, CONFIRMED = "Open", "Closed-pending", "Confirmed"
CLOSED = (PENDING, CONFIRMED)
EVENT, OVER_SHORT_ACCOUNT = "Cash Over/Short", "Cash Over and Short"
CONFIRM_TASK, KIND = "Day Close to Confirm", "Cash box day close"
CLOSE_EVENT = "close"
ADMIN_ROLE, ADMIN_ROLES = "SP Admin", ("SP Admin", "System Manager")
CASHIER_ROLES = ("SP Showroom Cashier", *ADMIN_ROLES)
PENNY = 0.005  # sp-allow-number: half a piastre, rounding


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def _check_cashier() -> None:
	if frappe.session.user != "Administrator" and not set(CASHIER_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the showroom cashier or the admin keeps the cash box."), frappe.PermissionError)


# --- the day's figures ------------------------------------------------------------------------------


def _gl_balance_before(account: str, day) -> float:
	(balance,) = frappe.db.sql(
		"""select coalesce(sum(debit - credit), 0) from `tabGL Entry`
		where account = %s and is_cancelled = 0 and posting_date < %s""",
		(account, day),
	)[0]
	return flt(balance)


def opening(doc) -> float:
	"""The last closing counted before this day; the first day starts from the books."""
	last = frappe.get_all(
		DAY,
		{"cash_account": doc.cash_account, "day": ("<", doc.day), "status": ("in", CLOSED)},
		["counted"],
		order_by="day desc",
		limit=1,
	)
	return flt(last[0].counted) if last else _gl_balance_before(doc.cash_account, doc.day)


def sales_in(account: str, day) -> float:
	"""Cash sales into the box: the showroom sales (SP-102) debit it through their invoices."""
	(amount,) = frappe.db.sql(
		"""select coalesce(sum(debit - credit), 0) from `tabGL Entry`
		where account = %s and is_cancelled = 0 and posting_date = %s
			and voucher_type in ('Sales Invoice', 'POS Invoice')""",
		(account, day),
	)[0]
	return flt(amount)


def movements(account: str, day) -> dict:
	"""The day's movements of the box, each with its record."""
	payments = frappe.get_all(
		PAYMENT,
		{
			"receiving_account": account,
			"work_date": day,
			"docstatus": 1,
			"status": ("in", ("Pending", "Confirmed")),
		},
		["name", "amount", "customer_name", "station", "status"],
	)
	expenses = frappe.get_all(
		EXPENSE,
		{"paid_from_account": account, "work_date": day, "docstatus": 1},
		["name", "amount", "expense_type", "expense_type_name", "note"],
	)
	deposits = frappe.get_all(
		TRANSFER,
		{
			"from_account": account,
			"work_date": day,
			"docstatus": 1,
			"status": ("in", ("Pending", "Confirmed")),
		},
		["name", "amount", "to_account", "status"],
	)
	return {"payments": payments, "expenses": expenses, "deposits": deposits}


def compute(doc) -> None:
	moves = movements(doc.cash_account, doc.day)
	doc.opening = opening(doc)
	doc.sales_in = sales_in(doc.cash_account, doc.day)
	doc.station_payments_in = sum(flt(r.amount) for r in moves["payments"])
	doc.expenses_out = sum(flt(r.amount) for r in moves["expenses"])
	doc.deposits_out = sum(flt(r.amount) for r in moves["deposits"])
	doc.expected_closing = (
		flt(doc.opening) + flt(doc.sales_in) + flt(doc.station_payments_in)
		- flt(doc.expenses_out) - flt(doc.deposits_out)
	)  # fmt: skip
	from smart_power.sp_finance.transit import days_held

	doc.days_held = days_held(doc.cash_account)


def validate(doc) -> None:
	from smart_power.sp_finance.customer_payment import showroom_box_account

	doc.company = doc.company or frappe.db.get_value("Account", doc.cash_account, "company")
	if doc.cash_account != showroom_box_account(doc.company):
		frappe.throw(_("{0} is not the showroom box.").format(doc.cash_account))
	other = frappe.db.get_value(
		DAY, {"cash_account": doc.cash_account, "status": OPEN, "name": ("!=", doc.name)}, "day"
	)
	if other and doc.status == OPEN:
		frappe.throw(
			_("The box already has an open day ({0}): close it first.").format(frappe.format(other, "Date"))
		)
	if doc.status == OPEN:
		compute(doc)


# --- cash held too long ------------------------------------------------------------------------------


def amount_limit() -> float:
	from smart_power.sp_core.services.settings import get_value

	return flt(get_value("showroom_box_cash_limit"))


def held(doc) -> dict:
	"""How the box stands against its limits (the page's banner and the rule)."""
	from smart_power.sp_finance.transfer import in_hand, pending_out
	from smart_power.sp_finance.transit import days_held, limit_days

	balance = in_hand(doc.cash_account)  # the deposits waiting for the admin are out of the box
	days, day_limit, cash_limit = days_held(doc.cash_account), limit_days(doc.cash_account), amount_limit()
	return {
		"balance": balance,
		"pending_deposits": pending_out(doc.cash_account),
		"days": days,
		"day_limit": day_limit,
		"cash_limit": cash_limit,
		"over_days": bool(day_limit and days > day_limit),
		"over_cash": bool(cash_limit and balance > cash_limit),
	}


def state(doc) -> dict:
	"""For the form: the day's records, the limits, and what this user may do."""
	moves = movements(doc.cash_account, doc.day) if doc.cash_account and doc.day else {}
	pending = (
		frappe.get_all(
			TRANSFER,
			{"from_account": doc.cash_account, "docstatus": 1, "status": "Pending"},
			["name", "amount", "to_account", "work_date"],
			order_by="work_date asc, creation asc",
		)
		if doc.cash_account
		else []
	)
	return {
		"moves": moves,
		"held": held(doc) if doc.cash_account else {},
		"pending_deposits": pending,
		"is_admin": is_admin(),
	}


# --- the day -------------------------------------------------------------------------------------------


@frappe.whitelist()
def open_today(company: str | None = None) -> str:
	"""The box's day to work on: the open one, else a new one for today."""
	from smart_power.sp_finance.customer_payment import showroom_box_account

	_check_cashier()
	company = (
		company
		or frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("SP Company Settings", "company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)
	account = showroom_box_account(company)
	if not account:
		frappe.throw(_("Company {0} has no showroom box (خزنة المعرض).").format(company))
	name = frappe.db.get_value(DAY, {"cash_account": account, "status": OPEN})
	if name:
		return name
	doc = frappe.get_doc({"doctype": DAY, "cash_account": account, "company": company, "day": today()})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


@frappe.whitelist(methods=["POST"])
def close_day(name: str, counted: float, reason: str | None = None) -> str:
	"""The cashier counts the box: the close waits for the admin (A1)."""
	from smart_power.rules import run

	_check_cashier()
	doc = frappe.get_doc(DAY, name)
	if doc.status != OPEN:
		frappe.throw(_("Day {0} is {1}, not open.").format(doc.name, _(doc.status)))
	compute(doc)
	doc.counted = flt(counted)
	doc.difference = flt(doc.counted - doc.expected_closing, 2)  # sp-allow-number: currency precision
	doc.reason = (reason or "").strip()
	if abs(doc.difference) > PENNY and not doc.reason:
		frappe.throw(
			_("The count is {0} off the expected {1}: give the reason.").format(
				frappe.format(doc.difference, "Currency"), frappe.format(doc.expected_closing, "Currency")
			),
			frappe.MandatoryError,
		)
	run(doc, CLOSE_EVENT)  # cash held too long: a warning, or (Block) no close until a deposit
	doc.status = PENDING
	doc.closed_by = frappe.session.user
	doc.reject_reason = None
	doc.flags.ignore_permissions = True
	doc.save()
	_confirm_task(doc)
	return doc.status


def _confirm_task(doc) -> None:
	from smart_power.sp_sales.quote_request import _users_with

	diff = flt(doc.difference)
	subject = _("Confirm the showroom box close of {0}: counted {1}").format(
		frappe.format(doc.day, "Date"), frappe.format(doc.counted, "Currency")
	)
	if abs(diff) > PENNY:
		subject += " (" + frappe.format(diff, "Currency") + ")"
	create_task(
		CONFIRM_TASK, DAY, doc.name, _users_with(ADMIN_ROLE) or ["Administrator"], subject, amount=diff
	)


# --- the confirmations centre (A1) ---------------------------------------------------------------------


def _pending(name: str):
	if not is_admin():
		frappe.throw(_("Only the admin confirms a day close."), frappe.PermissionError)
	doc = frappe.get_doc(DAY, name)
	if doc.status != PENDING:
		frappe.throw(_("Day {0} is {1}, not waiting.").format(doc.name, _(doc.status)))
	return doc


def _entry_kwargs(doc) -> dict:
	from smart_power.sp_finance.centers import SHOWROOM, center

	over_short = frappe.db.get_value(
		"Account", {"company": doc.company, "account_name": OVER_SHORT_ACCOUNT, "is_group": 0}
	)
	if not over_short:
		frappe.throw(_("Company {0} has no {1} account.").format(doc.company, _(OVER_SHORT_ACCOUNT)))
	short = flt(doc.difference) < 0
	cc = center(SHOWROOM, doc.company)
	return {
		"posting_date": doc.day,
		"cost_center": cc,
		"debit_center": cc,
		"credit_center": cc,
		"debit_account": over_short if short else doc.cash_account,
		"credit_account": doc.cash_account if short else over_short,
		"remark": _("Showroom box {0}: {1}").format(frappe.format(doc.day, "Date"), doc.reason or ""),
	}


@frappe.whitelist(methods=["POST"])
@audited("Confirmed", "SP Cash Box Day")  # X13 (SP-137)
def confirm(name: str) -> str | None:
	"""The admin checked the count: the difference posts (over or short); the day is confirmed."""
	from smart_power.sp_finance.posting import post

	doc = _pending(name)
	entry = None
	if abs(flt(doc.difference)) > PENNY:
		frappe.flags.sp_system_posting = True
		try:
			entry = post(EVENT, doc, abs(flt(doc.difference)), **_entry_kwargs(doc))
		finally:
			frappe.flags.sp_system_posting = False
	doc.db_set({"status": CONFIRMED, "confirmed_by": frappe.session.user, "journal_entry": entry})
	close_tasks(DAY, doc.name, CONFIRM_TASK)
	return entry


@frappe.whitelist(methods=["POST"])
@audited("Rejected", "SP Cash Box Day")  # X13 (SP-137)
def reject(name: str, reason: str) -> str:
	"""Back to the cashier with the reason; the day is open again."""
	from smart_power.notify import send

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for the rejection."), frappe.MandatoryError)
	doc = _pending(name)
	doc.db_set({"status": OPEN, "reject_reason": reason})
	close_tasks(DAY, doc.name, CONFIRM_TASK)
	if doc.closed_by:
		send(
			"receipt_rejected",
			[doc.closed_by],
			DAY,
			doc.name,
			_("The box close of {0} was sent back: {1}").format(frappe.format(doc.day, "Date"), reason),
		)
	return doc.name


def pending_items(filters: dict) -> list[dict]:
	where = {"status": PENDING}
	if filters.get("account"):
		where["cash_account"] = filters["account"]
	rows = frappe.get_all(
		DAY, where, ["name", "closed_by", "day", "cash_account", "difference", "counted"], order_by="day asc"
	)
	return [
		{
			"doctype": DAY,
			"name": r.name,
			"kind": _(KIND),
			"recorder": r.closed_by,
			"date": r.day,
			"account": r.cash_account,
			"amount": flt(r.difference),
			"photo": None,
			"station": None,
			"party": _("Counted {0}").format(frappe.format(r.counted, "Currency")),
		}
		for r in rows
	]


def preview(name: str) -> list[dict]:
	"""The over/short entry the confirmation will post (none when the count matches)."""
	from smart_power.sp_finance.posting import preview as posting_preview

	doc = frappe.get_doc(DAY, name)
	if abs(flt(doc.difference)) <= PENNY:
		return []
	return posting_preview(EVENT, doc, abs(flt(doc.difference)), **_entry_kwargs(doc))


# --- setup ---------------------------------------------------------------------------------------------


def seed_account_map(company: str) -> None:
	"""The Cash Over/Short row of the Account Map, once (each side is set by the close)."""
	from smart_power.constants import SETTINGS_DOCTYPE
	from smart_power.sp_finance.customer_payment import showroom_box_account

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if any(r.event == EVENT for r in settings.account_map):
		return
	over_short = frappe.db.get_value(
		"Account", {"company": company, "account_name": OVER_SHORT_ACCOUNT, "is_group": 0}
	)
	box = showroom_box_account(company)
	cc = frappe.get_cached_value("Company", company, "cost_center")
	if not (over_short and box and cc):
		return
	settings.append(
		"account_map",
		{
			"event": EVENT,
			"debit_account": over_short,
			"debit_center_rule": "From document",
			"debit_cost_center": cc,
			"credit_account": box,
			"credit_center_rule": "From document",
			"credit_cost_center": cc,
			"project_rule": "None",
			"note": "A short count; an over count posts the other way. The Showroom center.",
		},
	)
	settings.flags.ignore_permissions = True
	settings.save()
