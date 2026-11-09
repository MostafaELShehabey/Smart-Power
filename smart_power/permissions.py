"""Who sees what (SP-35).

Cost, supplier prices and the P1 list are for the cost roles only: the admin, the accountant,
quote creators, pricing managers, the purchase officer and supplier accounts (the
`sees_cost` flag in the role catalogue). Everyone else sees sale prices only.

This module holds the checks; the hooks in hooks.py apply them to ERPNext's own DocTypes, and
APIs strip the cost keys before they answer. More row and field rules (cases, quotes, stations,
leads, payments) join here as those DocTypes land (SP-35 dependencies).
"""

import frappe

from smart_power.sp_core.setup.role_catalogue import COST_ROLES

# Keys every API removes for users without cost access.
COST_KEYS = ("cost", "cost_date", "cost_supplier", "list_price", "list_date", "list_supplier", "margin_pct")


def can_see_cost(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(COST_ROLES) & set(frappe.get_roles(user)))


def strip_cost(data: dict, user: str | None = None) -> dict:
	"""A copy of data without the cost keys, unless the user may see cost."""
	if can_see_cost(user):
		return data
	return {k: v for k, v in data.items() if k not in COST_KEYS}


# --- Item Price: buying prices (List Price, P1 Cost, supplier prices) ---------------------------


def item_price_query_conditions(user: str | None = None) -> str:
	"""permission_query_conditions for Item Price: buying rows only for cost roles."""
	if can_see_cost(user):
		return ""
	return "(`tabItem Price`.buying = 0)"


def item_price_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""has_permission for Item Price. Controllers can only deny; True keeps the role's rights."""
	if doc.get("buying") and not can_see_cost(user):
		return False
	return True
