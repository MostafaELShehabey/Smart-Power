"""SP-112: Winch Debt Age Alert (months) from the seed, only when it is still empty."""

import frappe

from smart_power.sp_core.setup.seed import defaults


def execute():
	settings = "Smart Power Settings"
	if not frappe.db.get_single_value(settings, "winch_debt_age_months"):
		value = defaults()["settings"]["winch_debt_age_months"]["value"]
		frappe.db.set_single_value(settings, "winch_debt_age_months", value)
