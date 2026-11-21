"""SP-177: the Sales Partner party type, the referrer commission accounts and Account Map row on
each company with Smart Power's accounts, and the posting event setting."""

import frappe


def execute():
	from smart_power.sp_core.setup.seed import defaults
	from smart_power.sp_finance.accounts import OFFICIAL, seed_accounts
	from smart_power.sp_stations.commission import ensure_party_type, seed_account_map

	ensure_party_type()
	companies = {
		a.company
		for a in frappe.get_all("Account", filters={"sp_account_kind": OFFICIAL}, fields=["company"])
	}
	for company in sorted(companies):
		seed_accounts(company)
		seed_account_map(company)
	settings = "Smart Power Settings"
	if not frappe.db.get_single_value(settings, "referrer_commission_event"):
		value = defaults()["settings"]["referrer_commission_event"]["value"]
		frappe.db.set_single_value(settings, "referrer_commission_event", value)
