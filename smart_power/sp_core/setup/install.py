"""Install and migrate hooks."""

import frappe

from smart_power.constants import ADMIN_MODULE


def ensure_admin_module() -> None:
	"""The custom module that holds the admin's own customizations (SP-164)."""
	if frappe.db.exists("Module Def", ADMIN_MODULE):
		return
	frappe.get_doc(
		{"doctype": "Module Def", "module_name": ADMIN_MODULE, "app_name": "smart_power", "custom": 1}
	).insert(ignore_permissions=True)


def after_install() -> None:
	from smart_power.rules import sync_rule_settings
	from smart_power.sp_core.setup.locale import apply_branding, apply_locale
	from smart_power.sp_core.setup.seed import seed_list_values, seed_settings
	from smart_power.sp_sales.case_workflow import ensure_workflow_masters
	from smart_power.sp_sales.setup import apply_customer_naming
	from smart_power.sp_stock.prices import seed_price_lists

	ensure_admin_module()
	# before fixtures sync: the SP Case workflow fixture needs its states and actions (SP-46)
	ensure_workflow_masters()
	apply_locale()
	apply_branding()
	seed_list_values()
	seed_settings()
	sync_rule_settings()
	apply_customer_naming()
	seed_price_lists()


def after_sync() -> None:
	"""Runs on install after the fixtures (the SP roles) are in."""
	sync_role_profiles()


def sync_role_profiles() -> None:
	"""Create or correct the person-type role profiles from the role catalogue.

	A profile is saved only when its roles differ, because saving one queues a job that
	rewrites the roles of every user who has it.
	"""
	from smart_power.sp_core.setup.role_catalogue import PROFILES

	for p in PROFILES:
		expected = {r for r in p.roles() if frappe.db.exists("Role", r)}
		if frappe.db.exists("Role Profile", p.name):
			doc = frappe.get_doc("Role Profile", p.name)
			if {r.role for r in doc.roles} == expected:
				continue
		else:
			doc = frappe.new_doc("Role Profile")
			doc.role_profile = p.name
		doc.set("roles", [{"role": r} for r in sorted(expected)])
		doc.flags.ignore_permissions = True
		doc.save()


def before_migrate() -> None:
	from smart_power.devtools.fixtures import preflight

	preflight(raise_on_conflict=True)


def after_migrate() -> None:
	from smart_power.rules import sync_rule_settings

	ensure_admin_module()
	sync_role_profiles()
	sync_rule_settings()
