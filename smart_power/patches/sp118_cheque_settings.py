"""SP-118: the cheque settings from the seed, once (Cheque Due Alert days, Confirm Collected
Cheques at Once). A value the admin set is kept."""

import frappe

from smart_power.sp_core.setup.seed import defaults


def execute():
	settings = "Smart Power Settings"
	seed = defaults()["settings"]
	if not frappe.db.get_single_value(settings, "cheque_due_lead_days"):
		frappe.db.set_single_value(settings, "cheque_due_lead_days", seed["cheque_due_lead_days"]["value"])
	# a new Check reads 0 before anyone chose; this patch runs once, so it sets the default once
	frappe.db.set_single_value(settings, "cheque_auto_confirm", seed["cheque_auto_confirm"]["value"])
