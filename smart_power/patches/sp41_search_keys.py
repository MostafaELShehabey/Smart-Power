"""SP-41: the search key of the customers and items saved before it."""

import frappe


def execute():
	from smart_power.sp_core.search_key import key_of
	from smart_power.sp_core.setup.fields import ensure_fixture_fields

	for doctype in ("Customer", "Item"):
		ensure_fixture_fields(doctype, ("sp_search_key",))

	for c in frappe.get_all("Customer", fields=["name", "customer_name", "sp_mobile", "sp_mobile_2"]):
		frappe.db.set_value(
			"Customer",
			c.name,
			"sp_search_key",
			key_of(c.customer_name, c.sp_mobile, c.sp_mobile_2, c.name),
			update_modified=False,
		)
	for i in frappe.get_all("Item", fields=["name", "item_code", "item_name", "sp_name_ar", "sp_model"]):
		frappe.db.set_value(
			"Item",
			i.name,
			"sp_search_key",
			key_of(i.item_code, i.item_name, i.sp_name_ar, i.sp_model),
			update_modified=False,
		)
