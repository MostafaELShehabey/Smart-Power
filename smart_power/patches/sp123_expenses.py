"""SP-123: the Owner Current Account, the Petty Cash expense type and the Expense row of the
Account Map on each company with Smart Power's accounts."""

import frappe


def execute():
	from smart_power.sp_core.setup.seed import seed_list_values
	from smart_power.sp_finance.accounts import OFFICIAL, seed_accounts
	from smart_power.sp_finance.expenses import seed_account_map

	seed_list_values()
	companies = {
		a.company
		for a in frappe.get_all("Account", filters={"sp_account_kind": OFFICIAL}, fields=["company"])
	}
	for company in sorted(companies):
		seed_accounts(company)
		seed_account_map(company)
