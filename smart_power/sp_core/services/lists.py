"""Admin-maintained value lists (SP List Value, SP-32 / X4).

A list value is named "{list_name}-{code}", e.g. "Region-DAKHLA". Link fields point at
SP List Value and use `link_filters(list_name)` so their pickers show only the active values
of one list; old records keep showing a value after it is deactivated.
"""

import json

import frappe
from frappe import _

DOCTYPE = "SP List Value"


def list_names() -> list[str]:
	"""The list keys, in the order the X4 screen shows them."""
	options = frappe.get_meta(DOCTYPE).get_field("list_name").options or ""
	return [o for o in options.split("\n") if o]


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


@frappe.whitelist()
def get_list(list_name: str) -> list[dict]:
	"""Every value of one list, active or not, for the X4 screen."""
	frappe.has_permission(DOCTYPE, "read", throw=True)
	_check_list_name(list_name)
	return get_values(list_name, active_only=False)


@frappe.whitelist(methods=["POST"])
def reorder(list_name: str, names: list[str] | str) -> None:
	"""Save the order the admin dragged the values into: the first gets sort order 1."""
	frappe.has_permission(DOCTYPE, "write", throw=True)
	_check_list_name(list_name)
	if isinstance(names, str):
		names = json.loads(names)
	in_list = set(frappe.get_all(DOCTYPE, filters={"list_name": list_name}, pluck="name"))
	if set(names) != in_list:
		frappe.throw(_("The order must contain every value of the list {0} once.").format(_(list_name)))
	for position, name in enumerate(names, start=1):
		if frappe.db.get_value(DOCTYPE, name, "sort_order") != position:
			doc = frappe.get_doc(DOCTYPE, name)
			doc.sort_order = position
			doc.save()


@frappe.whitelist(methods=["POST"])
def set_active(name: str, active: int | str) -> None:
	"""Activate or deactivate one value (the X4 toggle)."""
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("write")
	doc.is_active = 1 if frappe.utils.cint(active) else 0
	doc.save()


def _check_list_name(list_name: str) -> None:
	if list_name not in list_names():
		frappe.throw(_("Unknown list {0}.").format(list_name))
