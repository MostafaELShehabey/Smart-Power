"""SP-122: the custody expense types (with their accounts) and the Petty Cash Expenses account."""

import frappe

from smart_power.sp_core.services.company import COMPANY_SETTINGS


def execute():
	from smart_power.sp_core.setup.seed import seed_list_values
	from smart_power.sp_finance.accounts import seed_accounts

	seed_list_values()
	company = frappe.db.get_single_value(COMPANY_SETTINGS, "company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if company:
		seed_accounts(company)
