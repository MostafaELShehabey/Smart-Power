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
	from smart_power.sp_core.documents import (
		seed_contract_template,
		seed_quote_template,
		seed_warranty_template,
	)
	from smart_power.sp_core.setup.locale import apply_branding, apply_locale
	from smart_power.sp_core.setup.print_setup import setup_printing
	from smart_power.sp_core.setup.seed import seed_list_values, seed_settings
	from smart_power.sp_quotes.quote_print import make_desk_default, seed_default_print_format
	from smart_power.sp_sales.case_workflow import ensure_workflow_masters
	from smart_power.sp_sales.quote_request import seed_request_fields
	from smart_power.sp_sales.setup import allow_repeated_items, apply_customer_naming
	from smart_power.sp_stations.setup import enable_stock_reservation
	from smart_power.sp_stations.station_workflow import ensure_workflow_masters as station_masters
	from smart_power.sp_stock.po_print import make_desk_default as make_po_desk_default
	from smart_power.sp_stock.prices import seed_price_lists
	from smart_power.sp_stock.purchase_orders import enable_batches
	from smart_power.sp_stock.warehouses import seed_warehouse_types

	ensure_admin_module()
	# before fixtures sync: the SP Case workflow fixture needs its states and actions (SP-46)
	ensure_workflow_masters()
	station_masters()  # and the SP Station workflow's (SP-73)
	apply_locale()
	apply_branding()
	from smart_power.sp_core.login import apply_login_settings

	apply_login_settings()  # SP-36
	frappe.db.set_single_value("System Settings", "default_app", "smart_power")  # SP-37
	seed_list_values()
	from smart_power.lists import seed_list_views

	seed_list_views()  # SP-45
	seed_request_fields()
	from smart_power.sp_site.commissioning import seed_commissioning_templates

	seed_commissioning_templates()  # SP-97
	seed_settings()
	sync_rule_settings()
	apply_customer_naming()
	allow_repeated_items()
	enable_stock_reservation()
	enable_batches()
	seed_price_lists()
	seed_warehouse_types()
	setup_printing()
	seed_quote_template()
	seed_contract_template()
	seed_warranty_template()  # SP-80
	seed_default_print_format()
	make_desk_default()
	make_po_desk_default()
	from smart_power.notify import sync_events

	sync_events()  # the notification event catalogue (SP-40)


def after_sync() -> None:
	"""Runs on install after the fixtures (the SP roles) are in."""
	sync_role_profiles()
	from smart_power.sp_stations.station_tabs import seed_tab_access

	seed_tab_access()  # SP-76: the map names the SP roles
	from smart_power.sp_stations.setup import seed_list_settings

	seed_list_settings()  # SP-77: the stations list's columns
	from smart_power.sp_stations.close import ensure_invoice_series

	ensure_invoice_series()  # SP-80: the final invoice's SINV-.YYYY.-.#### series


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
	from smart_power.permissions import sync_cost_permissions
	from smart_power.rules import sync_rule_settings

	ensure_admin_module()
	sync_role_profiles()
	sync_rule_settings()
	sync_cost_permissions()
	from smart_power.sp_sales.quote_list import sync_export_permissions

	sync_export_permissions()  # Q1 export (SP-64)
	from smart_power.notify import sync_events

	sync_events()  # the notification event catalogue (SP-40)
