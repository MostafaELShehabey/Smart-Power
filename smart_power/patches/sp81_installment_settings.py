"""SP-81: the instalment due alert days from the seed, once (a value the admin set is kept), and
the existing contracts' instalments allocated."""

import frappe

from smart_power.sp_core.setup.seed import defaults


def execute():
	settings = "Smart Power Settings"
	if not frappe.db.get_single_value(settings, "installment_due_lead_days"):
		value = defaults()["settings"]["installment_due_lead_days"]["value"]
		frappe.db.set_single_value(settings, "installment_due_lead_days", value)
	from smart_power.sp_stations.installments import allocate

	for station in frappe.get_all("SP Station", {"sales_order": ("is", "set")}, pluck="name"):
		allocate(station)
