"""SP-112: the Winch Discounts account and its Account Map row on each company with Smart Power's
accounts, Smart Power Winch Jobs Post from the seed, and the payment status of the jobs logged so far."""

import frappe


def execute():
	from smart_power.sp_core.setup.seed import defaults
	from smart_power.sp_finance.accounts import OFFICIAL, seed_accounts
	from smart_power.sp_winch.field_entry import ENTRY, JOB, seed_account_map
	from smart_power.sp_winch.receipts import refresh_job

	companies = {
		a.company
		for a in frappe.get_all("Account", filters={"sp_account_kind": OFFICIAL}, fields=["company"])
	}
	for company in sorted(companies):
		seed_accounts(company)
		seed_account_map(company)
	settings = "Smart Power Settings"
	if not frappe.db.get_single_value(settings, "winch_internal_revenue"):
		value = defaults()["settings"]["winch_internal_revenue"]["value"]
		frappe.db.set_single_value(settings, "winch_internal_revenue", value)
	for name in frappe.get_all(ENTRY, {"entry_kind": JOB}, pluck="name"):
		refresh_job(name)
