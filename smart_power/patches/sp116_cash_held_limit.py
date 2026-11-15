"""SP-116: Cash Held Limit (days) from the seed, only when it is still empty."""

import frappe

from smart_power.sp_core.setup.seed import defaults


def execute():
	settings = "Smart Power Settings"
	if not frappe.db.get_single_value(settings, "cash_held_limit_days"):
		value = defaults()["settings"]["cash_held_limit_days"]["value"]
		frappe.db.set_single_value(settings, "cash_held_limit_days", value)
