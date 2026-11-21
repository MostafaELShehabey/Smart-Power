"""SP-102: the showroom receipt's series, the walk-in customer, a showroom POS profile per company
and the discount rule."""

import frappe


def execute():
	from smart_power.rules import sync_rule_settings
	from smart_power.sp_finance.accounts import OFFICIAL
	from smart_power.sp_sales.showroom_sale import ensure_series, seed_pos_profile

	ensure_series()
	companies = {
		a.company
		for a in frappe.get_all("Account", filters={"sp_account_kind": OFFICIAL}, fields=["company"])
	}
	for company in sorted(companies):
		seed_pos_profile(company)
	sync_rule_settings()
