"""SP-68 (decision 67): there is no approval gate on a discount. The follow-up owner's limit warns
and flags the admin; it never blocks, so a "Block" level from SP-128 becomes "Warn"."""

import frappe


def execute():
	if frappe.db.get_value("SP Rule Setting", "discount_followup_max", "level") == "Block":
		frappe.db.set_value("SP Rule Setting", "discount_followup_max", "level", "Warn")
