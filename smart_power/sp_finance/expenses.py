"""A10 Expenses and petty cash (SP-123; ERD 7.4 Expense; data note 8-11-2026).

A direct expense (SP Expense: not from a custody, whose holders use their custody lines, SP-122):
date, amount, expense type, center, the station when it is a project's, what paid it, the receipt.

- **Center:** Project (the station's project on the Projects center), Showroom, Winch, Jumbo or
  Indirect. A project expense with no station, project petty cash among them, goes to the
  Indirect Pool and is split at month end (A16, SP-124).
- **Paid from:** an official account; the shop cash (the showroom box, خزنة المعرض); or the owner,
  posted to the Owner Current Account, a liability: what the company owes him (owner, 2026-11-21).
- **Posting** (on submit, at once): Account Map event "Expense", the debit from the expense type
  (its meta account; Petty Cash to Petty Cash Expenses), the credit what paid it. Each expense is
  listed in the Review centre (RV2), as SP-104 asks for the showroom's.
- **Who records** (owner, 2026-11-21): the admin and the accountant, any expense; the showroom
  cashier, shop-cash expenses only.

    expenses_by_center(filters)   the A10 list: totals by center and type (SP Expenses by Center
                                  and Type), from direct expenses, custody settlements and the
                                  winch's field expenses
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from smart_power.sp_finance.centers import (
	INDIRECT,
	JUMBO,
	PROJECTS,
	SHOWROOM,
	WINCH,
	center,
	station_center,
)

EXPENSE, EVENT, LIST = "SP Expense", "Expense", "Expense Type"
PROJECT = "Project"
CENTER_KEYS = {"Showroom": SHOWROOM, "Winch": WINCH, "Jumbo": JUMBO, "Indirect": INDIRECT}
OFFICIAL_KIND, SHOP, OWNER = "Official account", "Shop cash", "Company Owner"
OWNER_ACCOUNT = "Owner Current Account"
FULL_ROLES = ("SP Admin", "System Manager", "SP Accountant")


def records_any(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(FULL_ROLES) & set(frappe.get_roles(user)))


def _meta(expense_type: str) -> dict:
	raw = frappe.db.get_value("SP List Value", expense_type, "meta_json")
	if isinstance(raw, str):
		return json.loads(raw) if raw else {}
	return raw or {}


def _account(company: str, name: str | None) -> str | None:
	if not name:
		return None
	return frappe.db.get_value(
		"Account", {"company": company, "account_name": name, "is_group": 0}
	) or frappe.db.get_value("Account", {"company": company, "name": name, "is_group": 0})


def expense_account(doc) -> str:
	"""The expense type's account (its meta), else the Account Map's Expense row."""
	from smart_power.sp_core.services.settings import account_map

	account = _account(doc.company, _meta(doc.expense_type).get("account"))
	if account:
		return account
	row = account_map(EVENT)
	if row and row.debit_account:
		return row.debit_account
	frappe.throw(
		_("Set the account of expense type {0} (Lists) or the Expense row of the Account Map.").format(
			frappe.bold(doc.expense_type)
		)
	)


def _paid_from(doc) -> str:
	from smart_power.sp_finance.accounts import OFFICIAL
	from smart_power.sp_finance.customer_payment import showroom_box_account

	if doc.paid_from_kind == SHOP:
		account = showroom_box_account(doc.company)
		if not account:
			frappe.throw(_("Company {0} has no showroom box (خزنة المعرض).").format(doc.company))
		return account
	if doc.paid_from_kind == OWNER:
		account = _account(doc.company, OWNER_ACCOUNT)
		if not account:
			frappe.throw(_("Company {0} has no {1} account.").format(doc.company, _(OWNER_ACCOUNT)))
		return account
	if not doc.paid_from_account:
		frappe.throw(_("Choose the official account that paid it."), frappe.MandatoryError)
	kind, company = frappe.db.get_value("Account", doc.paid_from_account, ["sp_account_kind", "company"])
	if kind != OFFICIAL or company != doc.company:
		frappe.throw(_("{0} is not an official account of {1}.").format(doc.paid_from_account, doc.company))
	return doc.paid_from_account


def validate(doc) -> None:
	if frappe.db.get_value("SP List Value", doc.expense_type, "list_name") != LIST:
		frappe.throw(_("{0} is not an expense type.").format(frappe.bold(doc.expense_type)))
	if flt(doc.amount) <= 0:
		frappe.throw(_("The amount must be above zero."))
	if not records_any() and doc.paid_from_kind != SHOP:
		frappe.throw(
			_("The showroom cashier records expenses paid from the shop cash only."), frappe.PermissionError
		)
	if doc.center_type == PROJECT and doc.station:
		doc.project = frappe.db.get_value("SP Station", doc.station, "project")
		doc.cost_center = station_center(doc.company)
	else:
		doc.station = doc.project = None
		# a project's expense with no station joins the indirect pool (A16)
		key = INDIRECT if doc.center_type == PROJECT else CENTER_KEYS[doc.center_type]
		doc.cost_center = center(key, doc.company)
	doc.paid_from_account = _paid_from(doc)
	if doc.is_new() or not doc.recorded_by:
		doc.recorded_by = frappe.session.user
		doc.entry_time = now_datetime()


def _post_kwargs(doc) -> dict:
	return {
		"posting_date": doc.work_date,
		"cost_center": doc.cost_center,
		"project": doc.project,
		"debit_account": expense_account(doc),
		"credit_account": doc.paid_from_account,
		"debit_center": doc.cost_center,
		"credit_center": doc.cost_center,
		"remark": _("{0}: {1}").format(doc.expense_type, doc.note or doc.name),
	}


def on_submit(doc) -> None:
	"""Post at once (owner, 2026-11-21) and list it for review (RV2)."""
	from smart_power.sp_core.review_centre import raise_item
	from smart_power.sp_finance.posting import post

	frappe.flags.sp_system_posting = True  # the posting is the system's (SP-26)
	try:
		entry = post(EVENT, doc, flt(doc.amount), **_post_kwargs(doc))
	finally:
		frappe.flags.sp_system_posting = False
	doc.db_set("journal_entry", entry)
	label = frappe.db.get_value("SP List Value", doc.expense_type, "value_ar") or doc.expense_type
	raise_item(
		"Expense",
		doc,
		_("Expense {0} of {1} on {2}, paid from {3}").format(
			label,
			frappe.format(doc.amount, "Currency"),
			doc.station or doc.cost_center,  # the Indirect Pool, not "Project", for no station
			_(doc.paid_from_kind),
		),
		amount=flt(doc.amount),
	)


@frappe.whitelist()
def preview(doc: str | dict) -> list[dict]:
	"""The entry the expense will post, for the confirmation before Submit (nothing is saved)."""
	from smart_power.sp_finance.posting import preview as posting_preview

	doc = frappe.get_doc(frappe.parse_json(doc) if isinstance(doc, str) else doc)
	frappe.has_permission(EXPENSE, "submit", throw=True)
	validate(doc)
	return posting_preview(EVENT, doc, flt(doc.amount), **_post_kwargs(doc))


# --- setup -------------------------------------------------------------------------------------------


def seed_account_map(company: str) -> None:
	"""The Expense row of the Account Map, once: the debit is the expense type's account and the
	credit what paid it; the row's own accounts are the fallback. The station's project on the
	expense line."""
	from smart_power.constants import SETTINGS_DOCTYPE
	from smart_power.sp_finance.accounts import OFFICIAL

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if any(r.event == EVENT for r in settings.account_map):
		return
	debit = _account(company, "Miscellaneous Expenses")
	official = frappe.db.get_value(
		"Account",
		{"company": company, "sp_account_kind": OFFICIAL, "is_group": 0, "disabled": 0},
		order_by="account_name asc",
	)
	cc = frappe.get_cached_value("Company", company, "cost_center")
	if not (debit and official and cc):
		return
	settings.append(
		"account_map",
		{
			"event": EVENT,
			"debit_account": debit,
			"debit_center_rule": "From document",
			"debit_cost_center": cc,
			"credit_account": official,
			"credit_center_rule": "From document",
			"credit_cost_center": cc,
			"project_rule": "Debit side",
			"note": "The expense type's account and what paid it replace these; the center is the expense's.",
		},
	)
	settings.flags.ignore_permissions = True
	settings.save()


# --- the A10 list --------------------------------------------------------------------------------------


def expenses_by_center(filters: dict | None = None) -> list[dict]:
	"""Every expense, totalled by center and type (SP-123: paid from any custody, the shop cash or
	the owner): direct expenses, approved custody settlement lines and the winch's field expenses
	(BUG-19)."""
	filters = frappe._dict(filters or {})
	rows = _direct_expenses(filters) + _custody_expenses(filters) + _field_expenses(filters)
	if filters.get("center_type"):
		rows = [r for r in rows if r.center_type == filters.center_type]
	labels = dict(
		frappe.get_all(
			"SP List Value",
			{"name": ("in", list({r.expense_type for r in rows}) or [""])},
			["name", "value_ar"],
			as_list=True,
		)
	)
	totals: dict = {}
	for r in rows:
		key = (r.cost_center, r.expense_type)
		row = totals.setdefault(
			key,
			{
				"cost_center": r.cost_center,
				"center_type": _(r.center_type),
				"expense_type": labels.get(r.expense_type) or r.expense_type,
				"count": 0,
				"amount": 0.0,
			},
		)
		row["count"] += 1
		row["amount"] += flt(r.amount)
	return sorted(totals.values(), key=lambda r: (r["cost_center"] or "", r["expense_type"] or ""))


def _between(filters) -> dict:
	if filters.get("from_date") and filters.get("to_date"):
		return {"work_date": ("between", [filters.from_date, filters.to_date])}
	return {}


def _direct_expenses(filters) -> list:
	where = {"docstatus": 1, **_between(filters)}
	for key in ("expense_type", "station", "company"):
		if filters.get(key):
			where[key] = filters[key]
	return frappe.get_all(EXPENSE, where, ["cost_center", "center_type", "expense_type", "amount"])


def _custody_expenses(filters) -> list:
	"""The approved lines of submitted custody settlements, on the center they posted to."""
	where = {"parenttype": "SP Custody Settlement", "docstatus": 1, "decision": ("!=", "Reject")}
	where.update(_between(filters))
	for key in ("expense_type", "station"):
		if filters.get(key):
			where[key] = filters[key]
	lines = frappe.get_all(
		"SP Custody Settlement Line",
		where,
		["parent", "station", "cost_center", "center_type", "expense_type", "amount"],
	)
	companies = dict(
		frappe.get_all(
			"SP Custody Settlement",
			{"name": ("in", list({r.parent for r in lines}) or [""])},
			["name", "company"],
			as_list=True,
		)
	)
	out = []
	for r in lines:
		company = companies.get(r.parent)
		if filters.get("company") and company != filters.company:
			continue
		# as custody._expense_lines posts them: a station's on Projects, else the line's center
		cost_center = station_center(company) if r.station else r.cost_center
		out.append(
			frappe._dict(
				cost_center=cost_center,
				center_type=_center_type(cost_center, company),
				expense_type=r.expense_type,
				amount=r.amount,
			)
		)
	return out


def _field_expenses(filters) -> list:
	"""The winch and Jumbo field expenses (fuel …): posted on their vehicle's center when logged."""
	if filters.get("station"):
		return []  # a vehicle's running cost is not a station's
	where = {"entry_kind": "Expense", "is_opening": 0, **_between(filters)}
	for key in ("expense_type", "company"):
		if filters.get(key):
			where[key] = filters[key]
	rows = frappe.get_all(
		"SP Field Entry", where, ["vehicle", "cost_center", "company", "expense_type", "amount"]
	)
	kinds = dict(
		frappe.get_all(
			"Vehicle",
			{"name": ("in", list({r.vehicle for r in rows}) or [""])},
			["name", "sp_vehicle_type"],
			as_list=True,
		)
	)
	for r in rows:
		kind = kinds.get(r.vehicle)
		r.center_type = kind if kind in CENTER_KEYS else _center_type(r.cost_center, r.company)
	return rows


def _center_type(cost_center: str | None, company: str | None) -> str:
	"""The center a cost center is, in the list's terms (Project, Showroom, Winch, Jumbo, Indirect)."""
	for label, key in (("Project", PROJECTS), *[(k, v) for k, v in CENTER_KEYS.items()]):
		if cost_center and cost_center == center(key, company):
			return label
	return "Indirect"
