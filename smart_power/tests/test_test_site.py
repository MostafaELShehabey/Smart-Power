"""The tests keep to a site made for them (BUG-39)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.tests.utils import ensure_test_site


class TestTestSite(IntegrationTestCase):
	def test_a_working_site_stops_the_tests(self):
		with patch.object(frappe.local, "site", "sp.localhost"), self.assertRaises(SystemExit) as stop:
			ensure_test_site()
		self.assertIn("sp.localhost", str(stop.exception))
		self.assertIn("bench new-site test_sp", str(stop.exception))

	def test_a_test_site_runs_them(self):
		with patch.object(frappe.local, "site", "test_site"):
			ensure_test_site()

	def test_the_hook_is_the_same_check(self):
		self.assertIn("smart_power.tests.utils.ensure_test_site", frappe.get_hooks("before_tests"))
