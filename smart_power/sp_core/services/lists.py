"""Admin-maintained value lists (SP List Value, SP-32 / X4).

A list value is named "{list_name}-{code}", e.g. "Region-DAKHLA". Link fields point at
SP List Value and use `link_filters(list_name)` so their pickers show only the active values
of one list; old records keep showing a value after it is deactivated.
"""

import json

import frappe

DOCTYPE = "SP List Value"


def link_filters(list_name: str) -> str:
	"""The `link_filters` JSON for a Link field to one list (active values only)."""
	return json.dumps([[DOCTYPE, "list_name", "=", list_name], [DOCTYPE, "is_active", "=", 1]])


def get_values(list_name: str, active_only: bool = True) -> list[dict]:
	filters = {"list_name": list_name}
	if active_only:
		filters["is_active"] = 1
	return frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=["name", "code", "value_ar", "value_en", "parent_value", "is_active", "sort_order"],
		order_by="sort_order asc, value_ar asc",
	)


def by_code(list_name: str, code: str) -> str | None:
	"""Name of the list value with this code, e.g. by_code("System Type", "PUMP")."""
	return frappe.db.get_value(DOCTYPE, {"list_name": list_name, "code": code})
