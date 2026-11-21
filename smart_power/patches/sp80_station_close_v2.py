"""SP-80: the final invoice's yearly series, a first warranty certificate template, and the
Write-off row of the Account Map on each company with Smart Power's accounts."""

import frappe


def execute():
	from smart_power.sp_core.documents import seed_warranty_template
	from smart_power.sp_finance.accounts import OFFICIAL
	from smart_power.sp_stations.close import ensure_invoice_series, seed_account_map

	ensure_invoice_series()
	seed_warranty_template()
	companies = {
		a.company
		for a in frappe.get_all("Account", filters={"sp_account_kind": OFFICIAL}, fields=["company"])
	}
	for company in sorted(companies):
		seed_account_map(company)
