"""SP-28: warehouse types, and the warehouse tree for the Smart Power company if it exists already."""

import frappe

from smart_power.sp_core.services.company import COMPANY_SETTINGS
from smart_power.sp_stock.warehouses import seed_warehouse_types, seed_warehouses


def execute():
	seed_warehouse_types()
	company = frappe.db.get_single_value(COMPANY_SETTINGS, "company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if company:
		seed_warehouses(company)
