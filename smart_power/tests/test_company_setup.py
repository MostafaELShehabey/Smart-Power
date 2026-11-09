"""The Smart Power company through ERPNext's setup (SP-25)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.setup import company as setup
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()


class TestCompanySetup(IntegrationTestCase):
	def test_wizard_answers(self):
		args = setup.setup_args()
		self.assertEqual(
			(args["company_name"], args["company_abbr"], args["currency"], args["country"]),
			("Smart Power", "SP", "EGP", "Egypt"),
		)
		self.assertEqual((args["fy_start_date"], args["fy_end_date"]), ("2027-01-01", "2027-12-31"))
		self.assertFalse(args["enable_telemetry"])

	def test_links_x12_to_the_company(self):
		settings = frappe.get_single("SP Company Settings")
		settings.company = None
		settings.save()
		setup.link_company_settings("_Test Company")
		self.assertEqual(frappe.db.get_single_value("SP Company Settings", "company"), "_Test Company")

	def test_keeps_the_admins_choice(self):
		frappe.db.set_single_value("SP Company Settings", "company", "_Test Company")
		setup.link_company_settings("_Test Company 1")
		self.assertEqual(frappe.db.get_single_value("SP Company Settings", "company"), "_Test Company")

	def test_second_run_only_links(self):
		# Setup already done: the wizard must not run again.
		with (
			patch.object(frappe, "is_setup_complete", return_value=True),
			patch("frappe.desk.page.setup_wizard.setup_wizard.setup_complete") as wizard,
			patch.object(setup, "setup_args", return_value={"company_name": "_Test Company"}),
		):
			self.assertEqual(setup.complete_setup(), "_Test Company")
			wizard.assert_not_called()

	def test_failed_wizard_is_reported(self):
		with (
			patch.object(frappe, "is_setup_complete", return_value=False),
			patch(
				"frappe.desk.page.setup_wizard.setup_wizard.setup_complete",
				return_value={"status": "fail", "fail": "boom"},
			),
		):
			with self.assertRaises(frappe.ValidationError):
				setup.complete_setup()

	def test_set_up_site_without_the_company_gets_it(self):
		# e.g. a dev site that ERPNext's test data marked as set up
		with (
			patch.object(frappe, "is_setup_complete", return_value=True),
			patch("frappe.desk.page.setup_wizard.setup_wizard.setup_complete") as wizard,
			patch.object(setup, "create_company") as create,
			patch.object(setup, "setup_args", return_value={"company_name": "No Such Company SP25"}),
		):
			with self.assertRaises(frappe.ValidationError):  # the mock creates nothing
				setup.complete_setup()
			wizard.assert_not_called()
			create.assert_called_once()
