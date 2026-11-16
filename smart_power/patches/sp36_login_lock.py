"""SP-36: the number of failed sign-ins that lock an account (5), where it is still empty."""

import frappe


def execute():
	from smart_power.constants import SETTINGS_DOCTYPE
	from smart_power.sp_core.setup.seed import defaults

	if not frappe.db.get_single_value(SETTINGS_DOCTYPE, "login_lock_attempts"):
		value = defaults()["settings"]["login_lock_attempts"]["value"]
		frappe.db.set_single_value(SETTINGS_DOCTYPE, "login_lock_attempts", value)
