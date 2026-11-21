"""The Smart Power company (SP-25).

`complete_setup` runs ERPNext's setup wizard with Smart Power's values instead of clicking
through it, so every site (local, staging, production) gets the same company:

    bench --site <site> execute smart_power.sp_core.setup.company.complete_setup

It is safe to run again. When setup is already complete (done by hand, or by ERPNext's test
data on a dev site) but the company is missing, only the company and its fiscal year are
created, with ERPNext's own company step. Then the company is linked to X12 Company settings.
"""

import frappe
from frappe import _

from smart_power.sp_core.services.company import COMPANY_SETTINGS
from smart_power.sp_core.setup.seed import defaults
from smart_power.sp_stock.item import seed_item_groups
from smart_power.sp_stock.warehouses import seed_warehouses

SETUP_OK = "ok"


def setup_args() -> dict:
	"""The setup wizard's answers, from defaults.json."""
	return {k: v for k, v in defaults()["company"].items() if not k.startswith("_")}


def complete_setup() -> str:
	"""Create the company through ERPNext's setup wizard if setup is not done yet. Returns its name."""
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	args = setup_args()
	if not frappe.is_setup_complete():
		result = setup_complete(args) or {}
		if result.get("status") != SETUP_OK:
			frappe.throw(
				_("ERPNext setup did not finish: {0}").format(result.get("fail") or result),
				title=_("Setup failed"),
			)
	company = frappe.db.get_value("Company", {"company_name": args["company_name"]})
	if not company:
		create_company(args)
		company = frappe.db.get_value("Company", {"company_name": args["company_name"]})
	if not company:
		frappe.throw(_("Setup is complete but there is no company named {0}.").format(args["company_name"]))
	link_company_settings(company)
	seed_item_groups()
	seed_warehouses(company)
	from smart_power.sp_stock.stock_count import seed_count_schedule

	seed_count_schedule(company)  # SP-94
	from smart_power.sp_finance.accounts import seed_accounts

	seed_accounts(company)  # SP-26
	from smart_power.sp_finance.centers import seed_centers

	seed_centers(company)  # SP-27
	from smart_power.sp_finance.advances import seed_account_map

	seed_account_map(company)  # SP-121
	from smart_power.sp_finance.simple_record import seed_account_map as seed_simple_record

	seed_simple_record(company)  # SP-43
	from smart_power.sp_site.site_log import seed_account_map as seed_site_log

	seed_site_log(company)  # SP-96
	from smart_power.sp_winch.field_entry import seed_account_map as seed_field_entry

	seed_field_entry(company)  # SP-108
	from smart_power.sp_winch.crew_pay import seed_account_map as seed_crew_pay

	seed_crew_pay(company)  # SP-181
	from smart_power.sp_stations.commission import seed_account_map as seed_commission

	seed_commission(company)  # SP-177
	return company


def create_company(answers: dict) -> None:
	"""ERPNext's setup step for the fiscal year and company (existing records are skipped)."""
	from erpnext.setup.setup_wizard.operations.install_fixtures import install_company

	install_company(frappe._dict(answers))
	company = frappe.db.get_value("Company", {"company_name": answers["company_name"]})
	if company and not frappe.db.get_single_value("Global Defaults", "default_company"):
		frappe.db.set_single_value("Global Defaults", "default_company", company)


def link_company_settings(company: str) -> None:
	"""Point X12 at the company, unless the admin already chose one."""
	settings = frappe.get_single(COMPANY_SETTINGS)
	if settings.company:
		return
	settings.company = company
	settings.flags.ignore_permissions = True
	settings.save()
