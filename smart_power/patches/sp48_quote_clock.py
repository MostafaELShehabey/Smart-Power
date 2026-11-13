"""SP-48: seed the amber setting, and give open quote requests their due time."""

import frappe

from smart_power.sp_core.setup.seed import seed_settings
from smart_power.sp_sales.quote_clock import due_at


def execute():
	seed_settings()  # fills only empty settings, so the admin's values stay
	for case in frappe.get_all(
		"SP Case",
		filters={"quote_due_at": ("is", "not set"), "status": ("in", ("Quote request", "Draft"))},
		fields=["name", "creation"],
	):
		frappe.db.set_value(
			"SP Case", case.name, "quote_due_at", due_at(case.creation), update_modified=False
		)
