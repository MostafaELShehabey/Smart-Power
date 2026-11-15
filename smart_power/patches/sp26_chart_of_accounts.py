"""SP-26: the official accounts, the custody group, the other accounts and the modes of payment
for the Smart Power company, if it exists already."""

import frappe

from smart_power.sp_core.services.company import COMPANY_SETTINGS


def execute():
	from smart_power.sp_finance.accounts import seed_accounts

	company = frappe.db.get_single_value(COMPANY_SETTINGS, "company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if company:
		seed_accounts(company)
