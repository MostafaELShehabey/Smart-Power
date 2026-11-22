"""R5 Team commission (SP-143): each person's monthly commission, entered by the admin, and paid.

One SP Team Commission per company and month: a line per person with the amount the admin enters
(no formula, as agreed), a note, and whether it is paid. Station commissions from quotes are
separate and already sit in station cost (SP-58, SP-177).

    saving the amounts   "Team Commission": Dr Commission on Sales / Cr Commission Payable, on the
                         Indirect Pool center (the story's default), dated the month's last day.
                         A changed total reverses the entry and posts the new one.
    mark_paid(line)      "Team Commission Payment": Dr Commission Payable / Cr the official account
                         picked, dated the day it is paid. A paid line is locked.
    entered(company, m)  the month close's R5 row (SP-126): the month's sheet, if any

Every change is kept in the document's version history.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate, today

from smart_power.sp_finance.centers import INDIRECT, center
from smart_power.sp_finance.posting import JE, post, postings

DOCTYPE = "SP Team Commission"
EVENT, PAY_EVENT = "Team Commission", "Team Commission Payment"
EXPENSE_ACCOUNT, PAYABLE_ACCOUNT = "Commission on Sales", "Commission Payable"
MONEY_DIGITS = 2  # sp-allow-number: currency precision


def _account(company: str, account_name: str) -> str | None:
	return frappe.db.get_value("Account", {"company": company, "account_name": account_name, "is_group": 0})


def seed_account_map(company: str) -> None:
	"""The two Team Commission rows of the Account Map, once. The admin can change them."""
	from smart_power.constants import SETTINGS_DOCTYPE
	from smart_power.sp_finance.accounts import OFFICIAL

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	have = {r.event for r in settings.account_map}
	expense, payable = _account(company, EXPENSE_ACCOUNT), _account(company, PAYABLE_ACCOUNT)
	official = frappe.db.get_value(
		"Account",
		{"company": company, "sp_account_kind": OFFICIAL, "is_group": 0, "disabled": 0},
		order_by="account_name asc",
	)
	pool = center(INDIRECT, company)
	if not (expense and payable and official and pool):
		return
	rows = {
		EVENT: (expense, payable, "The month's team commission: an indirect cost, owed to the team."),
		PAY_EVENT: (payable, official, "A team commission paid: the account picked replaces the credit."),
	}
	for event, (debit, credit, note) in rows.items():
		if event in have:
			continue
		settings.append(
			"account_map",
			{
				"event": event,
				"debit_account": debit,
				"debit_center_rule": "Fixed",
				"debit_cost_center": pool,
				"credit_account": credit,
				"credit_center_rule": "Fixed",
				"credit_cost_center": pool,
				"project_rule": "None",
				"note": note,
			},
		)
	settings.flags.ignore_permissions = True
	settings.save()


# --- the document ---------------------------------------------------------------------------------


def validate(doc) -> None:
	doc.month = get_first_day(getdate(doc.month))
	other = frappe.db.get_value(
		DOCTYPE, {"company": doc.company, "month": doc.month, "name": ("!=", doc.name or "")}
	)
	if other:
		frappe.throw(_("The team commission of this month is already entered in {0}.").format(other))
	people = set()
	for row in doc.lines:
		if flt(row.amount) <= 0:
			frappe.throw(_("Row {0}: the amount must be above zero.").format(row.idx))
		if row.user in people:
			frappe.throw(_("Row {0}: {1} is entered twice.").format(row.idx, row.user))
		people.add(row.user)
	_keep_paid_lines(doc)
	doc.total = flt(sum(flt(r.amount) for r in doc.lines), MONEY_DIGITS)
	doc.paid_total = flt(sum(flt(r.amount) for r in doc.lines if r.paid), MONEY_DIGITS)
	doc.payable = flt(doc.total - doc.paid_total, MONEY_DIGITS)


def _keep_paid_lines(doc) -> None:
	"""A paid line is never changed or removed, and only mark_paid marks one paid."""
	before = doc.get_doc_before_save()
	old = {r.name: r for r in (before.lines if before else [])}
	now = {r.name: r for r in doc.lines}
	for name, row in old.items():
		if not row.paid:
			continue
		new = now.get(name)
		if not new or new.user != row.user or flt(new.amount) != flt(row.amount) or not new.paid:
			frappe.throw(_("{0}'s commission is paid: it cannot change.").format(row.full_name or row.user))
	if doc.flags.get("sp_paying"):
		return
	for row in doc.lines:
		if row.paid and not (old.get(row.name) and old[row.name].paid):
			frappe.throw(_("Mark a commission paid with Mark Paid, so its payment posts."))


def _accruals(doc) -> list[str]:
	return [n for n in postings(doc) if frappe.db.get_value(JE, n, "sp_posting_event") == EVENT]


def on_update(doc) -> None:
	"""The month's total posts as the commission expense; a new total replaces the old entry."""
	posted = _accruals(doc)
	posted_amount = sum(flt(frappe.db.get_value(JE, n, "total_debit")) for n in posted)
	if flt(posted_amount, MONEY_DIGITS) == flt(doc.total, MONEY_DIGITS):
		return
	_cancel(posted)
	entry = None
	if flt(doc.total) > 0:
		entry = post(
			EVENT,
			doc,
			doc.total,
			company=doc.company,
			posting_date=get_last_day(doc.month),
			remark=_("Team commission {0}").format(frappe.format(doc.month, "Date")),
		)
	doc.db_set("accrual_entry", entry, update_modified=False)


def _cancel(entries: list[str]) -> None:
	from smart_power.sp_finance.journal import allow_cancel

	for name in entries:
		entry = frappe.get_doc(JE, name)
		allow_cancel(entry)  # the commission changed: its entry goes and the new total posts
		entry.cancel()


def on_trash(doc) -> None:
	if any(r.paid for r in doc.lines):
		frappe.throw(_("Paid commissions are on this sheet: it cannot be deleted."))
	_cancel(_accruals(doc))


@frappe.whitelist(methods=["POST"])
def mark_paid(name: str, line: str, account: str, paid_on: str | None = None) -> str:
	"""Pay one person's commission from an official account; returns the payment entry."""
	from smart_power.sp_finance.accounts import OFFICIAL

	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("write")
	row = next((r for r in doc.lines if r.name == line), None)
	if not row:
		frappe.throw(_("Line {0} is not on {1}.").format(line, name))
	if row.paid:
		frappe.throw(_("{0}'s commission is already paid.").format(row.full_name or row.user))
	kind, company = frappe.db.get_value("Account", account, ["sp_account_kind", "company"]) or (None, None)
	if kind != OFFICIAL or company != doc.company:
		frappe.throw(_("Pay from one of the company's official accounts."))
	paid_on = getdate(paid_on or today())
	entry = post(
		PAY_EVENT,
		doc,
		row.amount,
		company=doc.company,
		posting_date=paid_on,
		credit_account=account,
		remark=_("Team commission paid to {0}").format(row.full_name or row.user),
	)
	row.update({"paid": 1, "paid_on": paid_on, "paid_from_account": account, "journal_entry": entry})
	doc.flags.sp_paying = True
	doc.save()
	doc.add_comment(
		"Info",
		_("{0}'s commission ({1}) paid from {2}: {3}").format(
			row.full_name or row.user, frappe.format(row.amount, "Currency"), account, entry
		),
	)
	return entry


def entered(company: str, month) -> str | None:
	"""The month's team commission sheet (the month close's R5 row)."""
	return frappe.db.get_value(DOCTYPE, {"company": company, "month": get_first_day(getdate(month))})
