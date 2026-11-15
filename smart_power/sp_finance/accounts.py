"""The chart of accounts for how Smart Power really holds money (SP-26, A7).

- 4 official accounts under Bank Accounts: Smart Power Bank Misr, Mohamed Soliman InstaPay, The
  Post, Vodafone Cash.
- Transit accounts (Cash) under Cash In Hand, one per person or channel holding cash: the
  showroom safe is seeded; a person's ("Cash with ...") is made from the User form.
- Custody accounts (Asset) under Custody, one per custody holder, also from the User form.
- The other accounts: customer advances (Agri Bank), consignment memo, indirect cost pool,
  commission payable, the revenue accounts (projects, showroom, winch, Jumbo, storage, advance
  fees); ERPNext's own Creditors, Write Off and Stock Adjustment are used as they are.
- Mode of Payment records with their default account.

Each money account carries its kind (Money Kind: Official / Transit / Custody / Other) and its
holder. Others see only their own transit and custody balances; official balances are the
admin's (permission query on Account and GL Entry, and my_balances for the profile, G6).
Seeding is idempotent: accounts already there (or renamed by the admin) are kept.
"""

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.sp_core.setup.seed import defaults

OFFICIAL, TRANSIT, CUSTODY, OTHER = "Official", "Transit", "Custody", "Other"
HOLDER_KINDS = (TRANSIT, CUSTODY)
# who sees every money account: the admin and the accounts people
SEES_ALL = ("SP Admin", "System Manager", "SP Accountant", "Accounts Manager")


def _spec() -> dict:
	return {k: v for k, v in defaults()["accounts"].items() if not k.startswith("_")}


def _group(company: str, name: str) -> str | None:
	abbr = frappe.get_cached_value("Company", company, "abbr")
	return frappe.db.get_value("Account", {"company": company, "is_group": 1, "account_name": name}) or (
		frappe.db.exists("Account", f"{name} - {abbr}") and f"{name} - {abbr}"
	)


def _account(company: str, account_name: str, parent: str, **values) -> str:
	existing = frappe.db.get_value("Account", {"company": company, "account_name": account_name})
	if existing:
		return existing
	parent_name = _group(company, parent)
	if not parent_name:
		frappe.throw(_("Company {0} has no account group {1}.").format(company, parent))
	doc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"company": company,
			"parent_account": parent_name,
			**{k: v for k, v in values.items() if v is not None},
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def ensure_account_fields() -> None:
	"""The Account fields from the fixtures, when a patch runs before the fixtures sync."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	if frappe.db.has_column("Account", "sp_account_kind") and frappe.db.has_column("Account", "sp_holder"):
		return
	fixture = frappe.get_file_json(frappe.get_app_path("smart_power", "fixtures", "custom_field.json"))
	rows = [r for r in fixture if r["dt"] == "Account"]
	for row in rows:
		if not frappe.db.exists("Custom Field", row["name"]):
			create_custom_field(
				"Account", {k: v for k, v in row.items() if k not in ("doctype", "name", "dt")}
			)


def seed_accounts(company: str) -> None:
	"""The official accounts, the custody group, the other accounts and the modes of payment."""
	ensure_account_fields()
	spec = _spec()
	group = spec["custody_group"]
	_account(company, group["account_name"], group["parent"], is_group=1)
	names = {}
	for row in spec["accounts"]:
		names[row["account_name"]] = _account(
			company,
			row["account_name"],
			row["parent"],
			account_type=row.get("account_type"),
			sp_account_kind=row["kind"],
		)
	for row in spec["modes_of_payment"]:
		_mode_of_payment(company, row, names.get(row["account"]))
	for row in spec["accounts"]:
		if row.get("bank"):
			bank_account(company, row["bank"], names[row["account_name"]], row["account_name"])


def bank_account(company: str, bank: str, account: str, title: str) -> str:
	"""The Bank Account record of an official account, for ERPNext's bank reconciliation (SP-116)."""
	existing = frappe.db.get_value("Bank Account", {"account": account, "is_company_account": 1})
	if existing:
		return existing
	if not frappe.db.exists("Bank", bank):
		frappe.get_doc({"doctype": "Bank", "bank_name": bank}).insert(ignore_permissions=True)
	abbr = frappe.get_cached_value("Company", company, "abbr")
	doc = frappe.get_doc(
		{
			"doctype": "Bank Account",
			# Bank Account names are "<account name> - <bank>": the company keeps them apart
			"account_name": f"{title} - {abbr}",
			"bank": bank,
			"account": account,
			"is_company_account": 1,
			"company": company,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _mode_of_payment(company: str, row: dict, account: str | None) -> None:
	if frappe.db.exists("Mode of Payment", row["mode"]):
		mode = frappe.get_doc("Mode of Payment", row["mode"])
	else:
		mode = frappe.get_doc(
			{"doctype": "Mode of Payment", "mode_of_payment": row["mode"], "type": row["type"]}
		)
	if account and not any(r.company == company for r in mode.accounts):
		mode.append("accounts", {"company": company, "default_account": account})
	mode.flags.ignore_permissions = True
	mode.save()


def mode_for_method(method: str | None) -> str | None:
	"""The Mode of Payment of an SP Payment Method list value (e.g. Payment Method-INSTAPAY)."""
	if not method:
		return None
	code = frappe.db.get_value("SP List Value", method, "code")
	mode = next((r["mode"] for r in _spec()["modes_of_payment"] if r["method"] == code), None)
	# only a mode that exists: a site not seeded yet, or one the admin removed, posts without it
	return mode if mode and frappe.db.exists("Mode of Payment", mode) else None


# --- a person's transit and custody accounts ---------------------------------------------------


def holder_account(user: str, kind: str, company: str) -> str:
	"""The person's transit or custody account; made once."""
	existing = frappe.db.get_value(
		"Account", {"company": company, "sp_holder": user, "sp_account_kind": kind, "is_group": 0}
	)
	if existing:
		return existing
	full_name = frappe.utils.get_fullname(user)
	if kind == TRANSIT:
		return _account(
			company,
			_("Cash with {0}").format(full_name),
			"Cash In Hand",
			account_type="Cash",
			sp_account_kind=TRANSIT,
			sp_holder=user,
		)
	return _account(
		company,
		_("Custody of {0}").format(full_name),
		_spec()["custody_group"]["account_name"],
		sp_account_kind=CUSTODY,
		sp_holder=user,
	)


def on_user_update(doc, method=None) -> None:
	"""User on_update: the ticked accounts are made for the company (X1)."""
	from smart_power.sp_core.services.company import COMPANY_SETTINGS

	if not (doc.get("sp_create_transit_account") or doc.get("sp_create_custody_account")):
		return
	company = frappe.db.get_single_value(COMPANY_SETTINGS, "company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if not company:
		return
	if doc.get("sp_create_transit_account"):
		holder_account(doc.name, TRANSIT, company)
	if doc.get("sp_create_custody_account"):
		holder_account(doc.name, CUSTODY, company)


# --- who sees which money ------------------------------------------------------------------------


def _sees_all(user: str) -> bool:
	# a posting made by the system on someone's action (e.g. a collected cheque) sees every account
	if frappe.flags.sp_system_posting:
		return True
	return user == "Administrator" or bool(set(SEES_ALL) & set(frappe.get_roles(user)))


def account_query_conditions(user: str | None = None) -> str:
	"""permission_query_conditions for Account: others never list an official account or someone
	else's transit or custody account."""
	user = user or frappe.session.user
	if _sees_all(user):
		return ""
	u = frappe.db.escape(user)
	return (
		"(ifnull(`tabAccount`.sp_account_kind, '') in ('', 'Other')"
		f" or (`tabAccount`.sp_account_kind in ('Transit', 'Custody') and `tabAccount`.sp_holder = {u}))"
	)


def account_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _sees_all(user) or (doc.get("sp_account_kind") or OTHER) == OTHER:
		return True
	return doc.get("sp_account_kind") in HOLDER_KINDS and doc.get("sp_holder") == user


def gl_query_conditions(user: str | None = None) -> str:
	"""permission_query_conditions for GL Entry: the same accounts as above."""
	user = user or frappe.session.user
	if _sees_all(user):
		return ""
	u = frappe.db.escape(user)
	return (
		"`tabGL Entry`.account not in (select name from `tabAccount` where"
		f" sp_account_kind = 'Official' or (sp_account_kind in ('Transit', 'Custody') and ifnull(sp_holder, '') != {u}))"
	)


@frappe.whitelist()
def my_balances() -> list[dict]:
	"""The signed-in person's own transit and custody balances (the profile, G6)."""
	from erpnext.accounts.utils import get_balance_on

	rows = frappe.get_all(
		"Account",
		filters={"sp_holder": frappe.session.user, "sp_account_kind": ("in", HOLDER_KINDS), "is_group": 0},
		fields=["name", "account_name", "sp_account_kind", "company", "account_currency"],
	)
	from smart_power.sp_finance.transit import days_held, limit_days

	out = []
	for r in rows:
		held = days_held(r.name) if r.sp_account_kind == TRANSIT else 0
		limit = limit_days(r.name) if r.sp_account_kind == TRANSIT else 0
		out.append(
			{
				**r,
				"balance": flt(get_balance_on(r.name, company=r.company, ignore_account_permission=True)),
				"days_held": held,
				"over": bool(limit and held > limit),
			}
		)
	return out
