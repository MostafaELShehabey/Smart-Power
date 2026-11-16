"""SP-37: everyone lands in Smart Power's own dock (System Settings default app), unless set."""

import frappe


def execute():
	if not frappe.db.get_single_value("System Settings", "default_app"):
		frappe.db.set_single_value("System Settings", "default_app", "smart_power")
