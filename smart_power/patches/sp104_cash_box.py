"""SP-104: the Cash Over and Short account, its Account Map row, the box limit and the rule."""

import frappe


def execute():
	from smart_power.rules import sync_rule_settings
	from smart_power.sp_core.setup.seed import defaults
	from smart_power.sp_finance.accounts import OFFICIAL, seed_accounts
	from smart_power.sp_finance.cash_box import seed_account_map

	companies = {
		a.company
		for a in frappe.get_all("Account", filters={"sp_account_kind": OFFICIAL}, fields=["company"])
	}
	for company in sorted(companies):
		seed_accounts(company)
		seed_account_map(company)
	settings = "Smart Power Settings"
	if not frappe.db.get_single_value(settings, "showroom_box_cash_limit"):
		value = defaults()["settings"]["showroom_box_cash_limit"]["value"]
		frappe.db.set_single_value(settings, "showroom_box_cash_limit", value)
	sync_rule_settings()
