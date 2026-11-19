"""SP-108: the winch service and vehicle running accounts and the field entry Account Map rows, on
each company that has Smart Power's accounts."""

import frappe


def execute():
	from smart_power.sp_finance.accounts import OFFICIAL, seed_accounts
	from smart_power.sp_winch.field_entry import seed_account_map

	companies = {
		a.company
		for a in frappe.get_all("Account", filters={"sp_account_kind": OFFICIAL}, fields=["company"])
	}
	for company in sorted(companies):
		seed_accounts(company)
		seed_account_map(company)
