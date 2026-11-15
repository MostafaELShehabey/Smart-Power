"""Quote-clock alerts every 15 minutes (SP-48).

For each open request (Quote request or Draft, no quote sent yet):
- amber: a reminder to the quote creator (every quote creator while nobody has taken it)
  and the admins;
- overdue: the quote_24h rule fires (SP Rule Hit + an open SP Review Item for the admin)
  and the same people are told.
Each case is alerted once per level. With the rule set to Off, nothing is sent or logged.
Alerts use Frappe's notification bell; SP-40 adds preferences and the mobile push.
"""

import frappe
from frappe import _

from smart_power.notify import send
from smart_power.rules import OFF, effective_level, evaluate, get_rule_setting, record_warning, registry
from smart_power.rules.sales import QUOTE_CLOCK_EVENT
from smart_power.sp_sales.quote_clock import AMBER, OVERDUE, clock, due_hours

RULE_KEY = "quote_24h"
OPEN_STATUSES = ("Quote request", "Draft")
QUOTE_CREATOR, ADMIN = "SP Quote Creator", "SP Admin"


def rule_is_off() -> bool:
	spec = registry().get(RULE_KEY)
	return spec is None or effective_level(spec, get_rule_setting(RULE_KEY)) == OFF


def check_quote_clock(now=None) -> None:
	"""Scheduler (every 15 minutes): alert on requests that turned amber or overdue since the last run."""
	if rule_is_off():
		return
	for case in frappe.get_all(
		"SP Case",
		filters={"status": ("in", OPEN_STATUSES), "quote_sent_at": ("is", "not set")},
		fields=["name", "creation", "quote_sent_at", "quote_alert", "quote_creator", "customer_name"],
	):
		state = clock(case, now)["state"]
		if state == OVERDUE and case.quote_alert != OVERDUE:
			doc = frappe.get_doc("SP Case", case.name)
			for hit in evaluate(doc, QUOTE_CLOCK_EVENT):
				record_warning(doc, hit)
			# "طلب تجاوز 24 ساعة" with the hours from Quote Due Within
			notify(case, _("Request over {2} hours: {0} ({1})"))  # sp-allow-number: placeholder
			frappe.db.set_value("SP Case", case.name, "quote_alert", OVERDUE, update_modified=False)
		elif state == AMBER and not case.quote_alert:
			notify(case, _("Quote due soon: {0} ({1})"))
			frappe.db.set_value("SP Case", case.name, "quote_alert", AMBER, update_modified=False)


def recipients(case) -> list[str]:
	"""The case's quote creator (or all quote creators while unclaimed) and the admins."""
	creators = [case.quote_creator] if case.get("quote_creator") else _users_with(QUOTE_CREATOR)
	return sorted(set(creators) | set(_users_with(ADMIN)))


def notify(case, subject: str) -> None:
	send(
		"request_overdue",
		recipients(case),
		"SP Case",
		case.name,
		subject.format(case.customer_name or case.name, case.name, f"{due_hours():g}"),
		from_user="Administrator",
	)


def _users_with(role: str) -> list[str]:
	users = frappe.get_all("Has Role", {"role": role, "parenttype": "User"}, pluck="parent")
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")
