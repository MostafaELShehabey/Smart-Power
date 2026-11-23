"""Winch and Jumbo rules (SP-109, SP-110)."""

from frappe import _

from smart_power.rules import BLOCK, WARN, Finding, RuleContext, rule

RULE_KEY = "field_entry_day_locked"
DAY_LOCKED = "DAY_LOCKED"  # what the mobile app reads


@rule(
	RULE_KEY,
	doctypes=("SP Field Entry",),
	category="Commercial",
	default_level=BLOCK,
	title="Field entry day locked",
	description="A winch or Jumbo entry can be added or changed only within the lock days after its "
	"work date (Field Entry Lock Days in Smart Power Settings), or while the day is reopened.",
	review_category="Late Entry",
)
def field_entry_day_locked(doc, ctx: RuleContext):
	from smart_power.sp_winch.field_lock import is_locked

	if doc.get("is_opening"):
		return None  # a debt from before go-live, opened by the opening balances (SP-160)
	before = doc.get_doc_before_save()
	days = {(doc.vehicle, doc.work_date)}
	if before:
		days.add((before.vehicle, before.work_date))
	if not any(is_locked(vehicle, day) for vehicle, day in days):
		return None
	return Finding(message=_("Day locked"), suggestion=_("Ask to reopen it."), data={"code": DAY_LOCKED})


UNUSUAL_EXPENSE = "field_expense_unusual"
REVIEW_EVENT = "field_review"  # computed with the review flags (SP-110), not on save
FACTOR, MIN_ENTRIES, HISTORY = 1.5, 3, 50  # sp-allow-number: defaults, the admin sets the limits


@rule(
	UNUSUAL_EXPENSE,
	doctypes=("SP Field Entry",),
	events=(REVIEW_EVENT,),
	category="Commercial",
	default_level=WARN,
	never_block=True,
	title="Unusual field expense",
	description="A winch or Jumbo expense above its type's average times average_factor (over the "
	"last entries of that type, once there are min_entries of them), or above the type's own "
	"threshold in by_type (expense type code: amount). Flagged for the field review, never a block.",
)
def field_expense_unusual(doc, ctx: RuleContext):
	import frappe
	from frappe.utils import flt

	if doc.entry_kind != "Expense" or not doc.expense_type:
		return None
	amount = flt(doc.amount)
	code = frappe.db.get_value("SP List Value", doc.expense_type, "code")
	threshold = flt((ctx.limits.get("by_type") or {}).get(code))
	if threshold and amount > threshold:
		return Finding(
			message=_("Above the {0} threshold").format(frappe.format(threshold, "Currency")),
			amount=amount,
			data={"threshold": threshold},
		)
	past = frappe.get_all(
		"SP Field Entry",
		filters={"entry_kind": "Expense", "expense_type": doc.expense_type, "name": ("!=", doc.name)},
		pluck="amount",
		order_by="work_date desc, creation desc",
		limit=HISTORY,
	)
	if len(past) < int(ctx.limits.get("min_entries") or MIN_ENTRIES):
		return None
	average = sum(flt(a) for a in past) / len(past)
	factor = flt(ctx.limits.get("average_factor")) or FACTOR
	if amount <= average * factor:
		return None
	return Finding(
		message=_("Above {0} times the average {1}").format(factor, frappe.format(average, "Currency")),
		amount=amount,
		data={"factor": factor, "average": average},
	)


OLD_DEBT = "winch_old_debt"


@rule(
	OLD_DEBT,
	doctypes=("SP Vehicle Booking",),
	category="Commercial",
	default_level=WARN,
	title="Booking for a customer with old winch debt",
	description="A new winch or Jumbo booking for an outside customer whose jobs are still unpaid after "
	"Winch Debt Age Alert (months, Smart Power Settings). A warning by default (SP-112); the admin can "
	"make it a block or turn it off.",
)
def winch_old_debt(doc, ctx: RuleContext):
	import frappe

	from smart_power.sp_winch.receivables import old_debt_of_phone

	if doc.for_kind != "Outside" or doc.status in ("Done", "Cancelled"):
		return None
	if not doc.is_new() and not doc.has_value_changed("customer_phone"):
		return None
	debt = old_debt_of_phone(doc.customer_phone)
	if not debt:
		return None
	return Finding(
		message=_("{0} still owes {1} on winch jobs since {2}.").format(
			debt.customer_name,
			frappe.format(debt.outstanding, "Currency"),
			frappe.format(debt.oldest, "Date"),
		),
		suggestion=_("Collect the old debt, or agree on it before the job."),
		amount=debt.outstanding,
	)
