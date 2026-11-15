"""Finance rules (SP-116 and on)."""

from frappe import _

from smart_power.rules import WARN, Finding, RuleContext, rule

# Checked by a daily job (sp_finance.transit.check_cash_held), not on save.
CASH_HELD_EVENT = "cash_held"
RULE_KEY = "cash_held_too_long"


@rule(
	RULE_KEY,
	doctypes=("Account",),
	events=(CASH_HELD_EVENT,),
	category="Commercial",
	default_level=WARN,
	never_block=True,
	title="Cash held too long",
	description="Cash in a person's transit account longer than its Max Days Held (or Cash Held "
	"Limit in Smart Power Settings) alerts the holder and the admin every day until it is deposited. "
	"A warning, never a block.",
	review_category="Rule Warning",
)
def cash_held_too_long(doc, ctx: RuleContext):
	import frappe

	from smart_power.sp_finance.transit import days_held, limit_days

	limit = limit_days(doc.name)
	held = days_held(doc.name)
	if not limit or held <= limit:
		return None
	holder = frappe.utils.get_fullname(doc.sp_holder) if doc.get("sp_holder") else doc.account_name
	return Finding(
		message=_("{0} has held {1} for {2} days (limit {3}).").format(
			holder,
			frappe.format(
				doc.flags.sp_balance or 0, {"fieldtype": "Currency", "options": doc.account_currency}
			),
			held,
			limit,
		),
		suggestion=_("Deposit it into an official account."),
		amount=doc.flags.sp_balance,
		highlight=True,
	)


@rule(
	"transfer_over_balance",
	doctypes=("SP Transfer",),
	category="Commercial",
	default_level=WARN,
	title="Transfer above the transit balance",
	description="A transfer from a transit account for more than the account holds. A warning by "
	"default (SP-117); the admin can make it a block.",
	review_category="Rule Warning",
)
def transfer_over_balance(doc, ctx: RuleContext):
	import frappe
	from erpnext.accounts.utils import get_balance_on
	from frappe.utils import flt

	if frappe.db.get_value("Account", doc.from_account, "sp_account_kind") != "Transit":
		return None
	balance = flt(get_balance_on(doc.from_account, ignore_account_permission=True))
	if flt(doc.amount) <= balance:
		return None
	return Finding(
		message=_("{0} holds {1}; the transfer is {2}.").format(
			doc.from_account, frappe.format(balance, "Currency"), frappe.format(doc.amount, "Currency")
		),
		suggestion=_("Check the amount, or record the missing receipts first."),
		amount=flt(doc.amount) - balance,
	)
