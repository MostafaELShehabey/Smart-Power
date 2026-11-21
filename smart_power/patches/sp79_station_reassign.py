"""SP-79: each station payment keeps the collection owner of its date."""

import frappe

from smart_power.sp_stations.reassign import owner_on


def execute():
	frappe.reload_doc("sp_finance", "doctype", "sp_customer_payment")
	frappe.reload_doc("sp_sales", "doctype", "sp_owner_history")
	for row in frappe.get_all(
		"SP Customer Payment",
		{"station": ("is", "set"), "collection_owner": ("is", "not set")},
		["name", "station", "work_date"],
	):
		frappe.db.set_value(
			"SP Customer Payment",
			row.name,
			"collection_owner",
			owner_on(row.station, row.work_date),
			update_modified=False,
		)
