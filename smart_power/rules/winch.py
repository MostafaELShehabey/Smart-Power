"""Winch and Jumbo rules (SP-109)."""

from frappe import _

from smart_power.rules import BLOCK, Finding, RuleContext, rule

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

	before = doc.get_doc_before_save()
	days = {(doc.vehicle, doc.work_date)}
	if before:
		days.add((before.vehicle, before.work_date))
	if not any(is_locked(vehicle, day) for vehicle, day in days):
		return None
	return Finding(message=_("Day locked"), suggestion=_("Ask to reopen it."), data={"code": DAY_LOCKED})
