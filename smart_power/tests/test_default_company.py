"""The desk's default company follows Global Defaults (BUG-34)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.setup import company as setup
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()

COMPANY, OTHER = "_Test Company", "_Test Company 1"


def desk_default() -> str | None:
	return frappe.defaults.get_global_default("company")


def set_up(global_defaults: str | None, desk: str | None) -> None:
	frappe.db.set_single_value("Global Defaults", "default_company", global_defaults)
	frappe.defaults.clear_default(key="company", parent="__default")
	if desk:
		frappe.db.set_default("company", desk)


class TestDefaultCompany(IntegrationTestCase):
	def test_a_site_without_a_default_gets_the_company_of_global_defaults(self):
		set_up(COMPANY, None)
		self.assertIsNone(desk_default())
		setup.ensure_default_company()
		self.assertEqual(desk_default(), COMPANY)

	def test_a_default_already_there_is_kept(self):
		set_up(COMPANY, OTHER)
		setup.ensure_default_company()
		self.assertEqual(desk_default(), OTHER)

	def test_nothing_is_set_without_a_company_in_global_defaults(self):
		set_up(None, None)
		setup.ensure_default_company()
		self.assertIsNone(desk_default())

	def test_a_company_that_is_gone_is_not_made_the_default(self):
		set_up("No Such Company BUG34", None)
		setup.ensure_default_company()
		self.assertIsNone(desk_default())

	def test_making_the_company_registers_it(self):
		# a site already set up (the dev site, or a setup done by hand) takes this path
		set_up(None, None)
		with patch("erpnext.setup.setup_wizard.operations.install_fixtures.install_company"):
			setup.create_company({"company_name": COMPANY})
		self.assertEqual(frappe.db.get_single_value("Global Defaults", "default_company"), COMPANY)
		self.assertEqual(desk_default(), COMPANY)

	def test_the_patch_registers_it(self):
		from smart_power.patches.bug34_default_company import execute

		set_up(COMPANY, None)
		execute()
		self.assertEqual(desk_default(), COMPANY)

	def test_the_stores_tree_opens_on_the_company(self):
		from frappe.desk.form.meta import get_meta

		self.assertEqual(
			frappe.get_hooks("doctype_tree_js").get("Warehouse"), ["public/js/warehouse_tree.js"]
		)
		tree_js = get_meta("Warehouse").as_dict().get("__tree_js") or ""
		self.assertIn("frappe.boot.sp_company", tree_js)
		self.assertIn("company.hidden = 1", tree_js)
