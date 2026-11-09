"""Arabic and Egyptian defaults (SP-22)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.setup.locale import apply_locale


class TestLocale(IntegrationTestCase):
	def test_apply_locale(self):
		apply_locale()
		ss = frappe.get_single("System Settings")
		self.assertEqual(
			(ss.language, ss.country, ss.time_zone, ss.date_format, ss.currency, ss.first_day_of_the_week),
			("ar", "Egypt", "Africa/Cairo", "dd-mm-yyyy", "EGP", "Saturday"),
		)
		self.assertEqual(frappe.db.get_default("currency"), "EGP")
		self.assertTrue(frappe.db.exists("Fiscal Year", {"year_start_date": "2027-01-01"}))

	def test_setup_wizard_hook_reapplies_locale(self):
		self.assertIn(
			"smart_power.sp_core.setup.locale.apply_locale", frappe.get_hooks("setup_wizard_complete")
		)
