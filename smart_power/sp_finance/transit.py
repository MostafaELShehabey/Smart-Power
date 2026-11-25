"""Cash held by a person (SP-116): how long the oldest unsettled cash has been in a transit account.

    oldest_open_date(account)   the date of the oldest cash still in the account (first in, first out)
    days_held(account)          days since then, counting that day (cash received on day 1 is
                                held 4 days on day 4)
    limit_days(account)         the account's Max Days Held, else Cash Held Limit (X6)

The daily job (check_cash_held) alerts the holder and the admin while cash is held past its limit,
until it is deposited; the "cash held too long" rule logs it (SP Rule Hit and a review item).
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, today

from smart_power.sp_finance.accounts import TRANSIT

PENNY = 0.005  # sp-allow-number: half a piastre, rounding
ADMIN_ROLE = "SP Admin"


def oldest_open_date(account: str):
	"""Match money out against the oldest money in; the first date with money left over."""
	rows = frappe.get_all(
		"GL Entry",
		filters={"account": account, "is_cancelled": 0},
		fields=["posting_date", "debit", "credit"],
		order_by="posting_date asc, creation asc",
	)
	queue, out = [], sum(flt(r.credit) for r in rows)
	for r in rows:
		if flt(r.debit):
			queue.append([getdate(r.posting_date), flt(r.debit)])
	for item in queue:
		used = min(item[1], out)
		item[1] -= used
		out -= used
		if item[1] > PENNY:
			return item[0]
	return None


def days_held(account: str, on=None) -> int:
	oldest = oldest_open_date(account)
	return date_diff(on or today(), oldest) + 1 if oldest else 0


def limit_days(account: str) -> int:
	from smart_power.sp_core.services.settings import get_value

	return cint(frappe.db.get_value("Account", account, "sp_max_days_held")) or cint(
		get_value("cash_held_limit_days")
	)


def transit_accounts() -> list:
	return frappe.get_all(
		"Account",
		filters={"sp_account_kind": TRANSIT, "is_group": 0, "disabled": 0},
		fields=["name", "account_name", "sp_holder", "company", "account_currency"],
	)


def check_cash_held() -> list[str]:
	"""Daily: every transit account holding cash past its limit alerts its holder and the admin."""
	from erpnext.accounts.utils import get_balance_on

	from smart_power.rules import OFF, effective_level, evaluate, get_rule_setting, record_warning, registry
	from smart_power.rules.finance import CASH_HELD_EVENT, RULE_KEY

	spec = registry().get(RULE_KEY)
	if spec and effective_level(spec, get_rule_setting(RULE_KEY)) == OFF:
		return []
	alerted = []
	for acc in transit_accounts():
		balance = flt(get_balance_on(acc.name, company=acc.company, ignore_account_permission=True))
		if balance <= PENNY:
			continue
		doc = frappe.get_doc("Account", acc.name)
		doc.flags.sp_balance = balance
		hits = evaluate(doc, CASH_HELD_EVENT)
		if not hits:
			continue
		for hit in hits:
			record_warning(doc, hit)
		# the rule's message in each reader's language (BUG-22)
		_alert(
			acc,
			balance,
			lambda doc=doc, hits=hits: (evaluate(doc, CASH_HELD_EVENT) or hits)[0].finding.message,
		)
		alerted.append(acc.name)
	return alerted


def _alert(acc, balance: float, message) -> None:
	from smart_power.notify import send
	from smart_power.sp_sales.quote_request import _users_with

	users = sorted({u for u in [acc.sp_holder, *_users_with(ADMIN_ROLE)] if u})
	if not users:
		return
	send(
		"cash_held_too_long",
		users,
		"Account",
		acc.name,
		lambda: _("Deposit the cash: {0}").format(message() if callable(message) else message),
		from_user="Administrator",
	)
