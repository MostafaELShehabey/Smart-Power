"""A3 Treasury (SP-116): every money account, who holds company cash and for how long.

    treasury(company)   the official accounts with their balances, the transit accounts with
                        holder, balance and days held (over the limit flagged), the custody accounts

The admin's page only: official balances are never shown to others (SP-26). Each row opens its
statement (General Ledger); an official account opens the bank reconciliation for its Bank
Account. Transfers (A4) come with SP-117.
"""

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.sp_finance.accounts import CUSTODY, OFFICIAL, TRANSIT
from smart_power.sp_finance.transit import days_held, limit_days

ADMIN_ROLES = ("SP Admin", "System Manager")


def _check_admin() -> None:
	if frappe.session.user != "Administrator" and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("The treasury is the admin's."), frappe.PermissionError)


@frappe.whitelist()
def treasury(company: str | None = None) -> dict:
	from erpnext.accounts.utils import get_balance_on

	from smart_power.sp_core.services.company import COMPANY_SETTINGS

	_check_admin()
	company = (
		company
		or frappe.db.get_single_value(COMPANY_SETTINGS, "company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)
	rows = frappe.get_all(
		"Account",
		filters={
			"company": company,
			"is_group": 0,
			"disabled": 0,
			"sp_account_kind": ("in", (OFFICIAL, TRANSIT, CUSTODY)),
		},
		fields=["name", "account_name", "sp_account_kind", "sp_holder", "account_currency"],
		order_by="account_name asc",
	)
	banks = dict(
		frappe.get_all(
			"Bank Account",
			filters={"account": ("in", [r.name for r in rows] or [""]), "is_company_account": 1},
			fields=["account", "name"],
			as_list=True,
		)
	)
	out = {OFFICIAL: [], TRANSIT: [], CUSTODY: []}
	for r in rows:
		row = {
			"account": r.name,
			"account_name": r.account_name,
			"currency": r.account_currency,
			"balance": flt(get_balance_on(r.name, company=company, ignore_account_permission=True)),
			"holder": r.sp_holder,
			"holder_name": frappe.utils.get_fullname(r.sp_holder) if r.sp_holder else "",
			"bank_account": banks.get(r.name),
		}
		if r.sp_account_kind == TRANSIT:
			row["days_held"] = days_held(r.name) if row["balance"] > 0 else 0
			row["limit"] = limit_days(r.name)
			row["over"] = bool(row["limit"] and row["days_held"] > row["limit"])
		out[r.sp_account_kind].append(row)
	return {
		"company": company,
		"official": out[OFFICIAL],
		"transit": sorted(out[TRANSIT], key=lambda r: (-r["days_held"], r["account_name"])),
		"custody": out[CUSTODY],
		"totals": {k.lower(): sum(r["balance"] for r in v) for k, v in out.items()},
	}
