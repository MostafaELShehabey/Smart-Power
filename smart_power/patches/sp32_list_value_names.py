"""SP-32: list values are named "{list_name}-{code}" instead of "LV-#####".

Renaming updates every Link that points at the old name (margin ranges, rule settings).
"""

import frappe


def execute():
	frappe.reload_doc("sp_core", "doctype", "sp_list_value")
	for row in frappe.get_all("SP List Value", fields=["name", "list_name", "code"]):
		new_name = f"{row.list_name}-{row.code}"
		if row.name == new_name:
			continue
		if frappe.db.exists("SP List Value", new_name):
			raise frappe.ValidationError(f"Cannot rename {row.name}: {new_name} already exists.")
		frappe.rename_doc("SP List Value", row.name, new_name, force=True, show_alert=False)
