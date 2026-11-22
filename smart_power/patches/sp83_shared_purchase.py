"""SP-83: the Shared Purchases account and the Shared Purchase Split row of the Account Map on each
company with Smart Power's accounts."""

import frappe


def execute():
	from smart_power.sp_finance.accounts import OFFICIAL, seed_accounts
	from smart_power.sp_stock.shared_purchase import seed_account_map

	companies = {
		a.company
		for a in frappe.get_all("Account", filters={"sp_account_kind": OFFICIAL}, fields=["company"])
	}
	for company in sorted(companies):
		seed_accounts(company)
		seed_account_map(company)
