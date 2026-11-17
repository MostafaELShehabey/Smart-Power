"""SP-96: the site stages, the labour and materials accounts and the Site Labour Account Map row,
on each company that has Smart Power's accounts."""

import frappe


def execute():
	from smart_power.sp_core.setup.seed import seed_list_values
	from smart_power.sp_finance.accounts import OFFICIAL, seed_accounts
	from smart_power.sp_site.site_log import seed_account_map

	seed_list_values()
	companies = {
		a.company
		for a in frappe.get_all("Account", filters={"sp_account_kind": OFFICIAL}, fields=["company"])
	}
	for company in sorted(companies):
		seed_accounts(company)
		seed_account_map(company)
