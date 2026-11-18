"""Pickers (SP-44, components 5 and 6): what a center or a money account field offers.

center_picker    the company's financial centers (SP-27): Projects, Showroom, Winch, Jumbo,
                 Indirect Pool
account_picker   the official accounts and the user's own transit and custody accounts (SP-26)
"""

import frappe

from smart_power.sp_finance.accounts import CUSTODY, OFFICIAL, TRANSIT

CENTER_FIELDS = ("center_projects", "center_showroom", "center_winch", "center_jumbo", "center_indirect")


def _company(filters) -> str | None:
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	return filters.get("company") or frappe.defaults.get_user_default("Company")


@frappe.whitelist()
def center_picker(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | str | None = None
) -> list:
	"""The company's financial centers (the five of Smart Power Settings)."""
	from smart_power.constants import SETTINGS_DOCTYPE

	frappe.has_permission("Cost Center", "read", throw=True)
	company = _company(filters)
	settings = frappe.get_cached_doc(SETTINGS_DOCTYPE)
	names = [settings.get(f) for f in CENTER_FIELDS if settings.get(f)]
	# a new vehicle's own center joins them (SP-106)
	names += frappe.get_all("Vehicle", {"sp_cost_center": ("is", "set")}, pluck="sp_cost_center")
	return frappe.get_all(
		"Cost Center",
		filters={"name": ("in", names or [""]), "company": company, "is_group": 0},
		or_filters={"name": ("like", f"%{txt}%"), "cost_center_name": ("like", f"%{txt}%")},
		fields=["name", "cost_center_name"],
		as_list=True,
		start=int(start),
		page_length=int(page_len),
	)


def picker_accounts(company: str, user: str | None = None) -> list[str]:
	"""The official accounts and the user's own transit and custody accounts."""
	user = user or frappe.session.user
	base = {"company": company, "is_group": 0, "disabled": 0}
	return frappe.get_all(
		"Account", filters={**base, "sp_account_kind": OFFICIAL}, pluck="name"
	) + frappe.get_all(
		"Account",
		filters={**base, "sp_account_kind": ("in", (TRANSIT, CUSTODY)), "sp_holder": user},
		pluck="name",
	)


@frappe.whitelist()
def account_picker(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | str | None = None
) -> list:
	"""Money accounts: the 4 official ones and the user's own transit and custody accounts."""
	names = picker_accounts(_company(filters))
	return frappe.get_all(
		"Account",
		filters={"name": ("in", names or [""])},
		or_filters={"name": ("like", f"%{txt}%"), "account_name": ("like", f"%{txt}%")},
		fields=["name", "account_name"],
		as_list=True,
		order_by="sp_account_kind asc, account_name asc",
		start=int(start),
		page_length=int(page_len),
		ignore_permissions=True,  # a holder may not read the Account list; these are the ones he may use
	)
