"""SP-181: the Worker Advances and Crew Salaries accounts and their Account Map rows on each company
with Smart Power's accounts, and Worker Advance Repayment from the seed when it is still empty."""

import frappe


def execute():
	from smart_power.sp_core.setup.seed import defaults
	from smart_power.sp_finance.accounts import OFFICIAL, seed_accounts
	from smart_power.sp_winch.crew_pay import seed_account_map

	companies = {
		a.company
		for a in frappe.get_all("Account", filters={"sp_account_kind": OFFICIAL}, fields=["company"])
	}
	for company in sorted(companies):
		seed_accounts(company)
		seed_account_map(company)
	settings = "Smart Power Settings"
	if not frappe.db.get_single_value(settings, "worker_advance_repayment"):
		value = defaults()["settings"]["worker_advance_repayment"]["value"]
		frappe.db.set_single_value(settings, "worker_advance_repayment", value)
