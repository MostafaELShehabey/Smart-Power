"""Fixture ownership on the server side (SP-164).

Records the admin makes with Customize Form, Print Format Builder, Notification and the
other no-code tools are tagged with the "Smart Power Admin" module, so they are never
exported as developer fixtures and a deploy never overwrites them. Developer names
(sp_ fields, "SP " roles, profiles and workflows) are reserved for the developer.
"""

import frappe
from frappe import _

from smart_power.constants import ADMIN_MODULE, DEV_FIELD_PREFIX, DEV_NAME_PREFIX, SP_MODULES


def _developer_context() -> bool:
	return bool(
		frappe.conf.developer_mode
		or frappe.flags.in_install
		or frappe.flags.in_migrate
		or frappe.flags.in_patch
		or frappe.flags.in_fixtures
		or frappe.flags.in_test
	)


def tag_admin_owned(doc, method=None) -> None:
	"""before_insert/validate on module-owned DocTypes."""
	if _developer_context():
		return
	if not doc.get("module"):
		doc.module = ADMIN_MODULE
	if doc.module in SP_MODULES and doc.is_new():
		frappe.throw(
			_("Module {0} is reserved for developer changes. Use {1}.").format(doc.module, ADMIN_MODULE)
		)
	if doc.doctype == "Custom Field" and (doc.fieldname or "").startswith(DEV_FIELD_PREFIX) and doc.is_new():
		frappe.throw(
			_("Field names starting with {0} are reserved for developer fields.").format(DEV_FIELD_PREFIX)
		)


def guard_dev_names(doc, method=None) -> None:
	"""before_insert on Role, Role Profile and Workflow: "SP " names are developer-owned."""
	if _developer_context():
		return
	if (doc.name or doc.get(_name_field(doc)) or "").startswith(DEV_NAME_PREFIX):
		frappe.throw(
			_('Names starting with "{0}" are reserved for developer records. Choose another name.').format(
				DEV_NAME_PREFIX.strip()
			)
		)


def _name_field(doc) -> str:
	return {"Role": "role_name", "Role Profile": "role_profile", "Workflow": "workflow_name"}.get(
		doc.doctype, "name"
	)
