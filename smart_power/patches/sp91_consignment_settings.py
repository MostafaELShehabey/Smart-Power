"""SP-91: the consignment low-balance threshold from the seed, once (a value the admin set is
kept), and the notification event for it."""

import frappe

from smart_power.sp_core.setup.seed import defaults


def execute():
	settings = "Smart Power Settings"
	if not frappe.db.get_single_value(settings, "consignment_low_balance"):
		value = defaults()["settings"]["consignment_low_balance"]["value"]
		frappe.db.set_single_value(settings, "consignment_low_balance", value)
	from smart_power.notify import sync_events

	sync_events()
