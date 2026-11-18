"""SP-82: the purchase orders' list tabs, and the status of the orders that already exist."""

import frappe


def execute():
	from frappe.utils.fixtures import sync_fixtures

	from smart_power.lists import seed_list_views
	from smart_power.sp_stock.purchase_orders import enable_batches, refresh_progress

	sync_fixtures("smart_power")  # the new fields come with the fixtures, synced after patches
	seed_list_views()
	enable_batches()
	for name in frappe.get_all("Purchase Order", pluck="name"):
		refresh_progress(frappe.get_doc("Purchase Order", name), update=True)
