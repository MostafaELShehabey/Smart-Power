"""SP-148: the mobile API's rate limit from the seed, when it is still empty."""

import frappe

from smart_power.sp_core.setup.seed import defaults


def execute():
	frappe.reload_doc("sp_core", "doctype", "smart_power_settings")
	frappe.reload_doc("sp_core", "doctype", "sp_mobile_device")
	if not frappe.db.get_single_value("Smart Power Settings", "mobile_rate_limit"):
		value = defaults()["settings"]["mobile_rate_limit"]["value"]
		frappe.db.set_single_value("Smart Power Settings", "mobile_rate_limit", value)
