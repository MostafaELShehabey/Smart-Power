"""SP-71: Case Inactivity Alert (days) from the seed when it is still empty, the rule's level and
its notification event."""

import frappe

from smart_power.sp_core.setup.seed import defaults


def execute():
	from smart_power.notify import sync_events
	from smart_power.rules import sync_rule_settings

	frappe.reload_doc("sp_sales", "doctype", "sp_case")
	settings = "Smart Power Settings"
	if not frappe.db.get_single_value(settings, "case_inactivity_days"):
		value = defaults()["settings"]["case_inactivity_days"]["value"]
		frappe.db.set_single_value(settings, "case_inactivity_days", value)
	sync_rule_settings()
	sync_events()
