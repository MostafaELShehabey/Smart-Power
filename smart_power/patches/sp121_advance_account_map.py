"""SP-121: the Account Map rows of the Agri Bank advances (Customer Advance, Advance Repayment,
Advance Fee), once; a row the admin already has is kept."""

import frappe

from smart_power.sp_core.services.company import COMPANY_SETTINGS


def execute():
	from smart_power.sp_finance.advances import seed_account_map

	company = frappe.db.get_single_value(COMPANY_SETTINGS, "company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if company:
		seed_account_map(company)
