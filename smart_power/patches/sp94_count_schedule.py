"""SP-94: the seed's count schedule (main store monthly, showroom store weekly) for each company
that has those stores, where the admin has not scheduled them already."""

import frappe

from smart_power.sp_stock.stock_count import seed_count_schedule


def execute():
	frappe.reload_doc("sp_stock", "doctype", "sp_count_schedule")
	frappe.reload_doc("sp_core", "doctype", "smart_power_settings")
	for company in frappe.get_all("Company", pluck="name"):
		seed_count_schedule(company)
