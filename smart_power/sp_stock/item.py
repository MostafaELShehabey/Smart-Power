"""Item catalogue rules (SP-29, I1)."""

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.nestedset import get_root_of

from smart_power.sp_core.setup.seed import defaults

# (lower field, upper field): a spec pair where the first can never exceed the second.
SPEC_PAIRS = (
	("sp_mppt_min", "sp_mppt_max"),
	("sp_vmp", "sp_voc"),
	("sp_imp", "sp_isc"),
)


def validate(doc, method=None):
	"""Item validate hook: refuse spec values that cannot be true; take the group's price category."""
	if not doc.get("sp_price_age_category") and doc.item_group:
		doc.sp_price_age_category = frappe.get_cached_value(
			"Item Group", doc.item_group, "sp_price_age_category"
		)
	for low, high in SPEC_PAIRS:
		if flt(doc.get(low)) and flt(doc.get(high)) and flt(doc.get(low)) > flt(doc.get(high)):
			frappe.throw(
				_("{0} cannot be higher than {1}.").format(
					_(doc.meta.get_label(low)), _(doc.meta.get_label(high))
				),
				title=_("Check the specs"),
			)


def seed_item_groups() -> None:
	"""Create the catalogue categories under ERPNext's root item group, if missing.

	The root exists once ERPNext's setup has run, so this is called from complete_setup and a
	patch; on a site without it, it does nothing.
	"""
	root = get_root_of("Item Group")
	if not root:
		return
	spec = defaults()["item_groups"]
	for name in spec["names"]:
		if frappe.db.exists("Item Group", name):
			continue
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": name, "parent_item_group": root, "is_group": 0}
		).insert(ignore_permissions=True)
	from smart_power.sp_stock.item_codes import seed_group_codes
	from smart_power.sp_stock.prices import seed_price_categories

	seed_price_categories()
	seed_child_groups(spec.get("children") or {})  # after the categories they share
	seed_group_codes()  # SP-165
	from smart_power.sp_quotes.special_lines import seed_service_items

	seed_service_items()  # SP-58
	from smart_power.sp_quotes.calc_templates import seed_calc_templates

	seed_calc_templates()  # SP-56: its lines pick items from these groups


def seed_child_groups(children: dict[str, list[str]]) -> None:
	"""SP-56: groups under a category (motors and pumps under pumps …). The parent becomes a
	group; a child shares its parent's price category."""
	for parent, names in children.items():
		if not frappe.db.exists("Item Group", parent):
			continue
		if not frappe.db.get_value("Item Group", parent, "is_group"):
			group = frappe.get_doc("Item Group", parent)
			group.is_group = 1
			group.save(ignore_permissions=True)
		for name in names:
			if not frappe.db.exists("Item Group", name):
				frappe.get_doc(
					{
						"doctype": "Item Group",
						"item_group_name": name,
						"parent_item_group": parent,
						"is_group": 0,
					}
				).insert(ignore_permissions=True)
			category = frappe.db.get_value("Item Group", parent, "sp_price_age_category")
			if category and not frappe.db.get_value("Item Group", name, "sp_price_age_category"):
				frappe.db.set_value("Item Group", name, "sp_price_age_category", category)
