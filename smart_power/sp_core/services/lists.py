"""Admin-maintained value lists (SP List Value)."""

import frappe


def get_values(list_name: str, active_only: bool = True) -> list[dict]:
	filters = {"list_name": list_name}
	if active_only:
		filters["is_active"] = 1
	return frappe.get_all(
		"SP List Value",
		filters=filters,
		fields=["name", "code", "value_ar", "value_en", "parent_value"],
		order_by="sort_order asc, value_ar asc",
	)


def by_code(list_name: str, code: str) -> str | None:
	"""Name of the list value with this code, e.g. by_code("System Type", "PUMP")."""
	return frappe.db.get_value("SP List Value", {"list_name": list_name, "code": code})
