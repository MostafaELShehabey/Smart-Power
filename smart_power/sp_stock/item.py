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
	"""Item validate hook: refuse spec values that cannot be true."""
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
	for name in defaults()["item_groups"]["names"]:
		if frappe.db.exists("Item Group", name):
			continue
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": name, "parent_item_group": root, "is_group": 0}
		).insert(ignore_permissions=True)
