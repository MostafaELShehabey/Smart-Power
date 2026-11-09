"""List values named in the SP-32 story are seeded."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services import lists
from smart_power.tests.test_lists import DT, make


class TestSeededLists(IntegrationTestCase):
	def test_values_named_in_the_story(self):
		self.assertEqual(lists.by_code("Lost Reason", "PRICE_CHECK_ONLY"), "Lost Reason-PRICE_CHECK_ONLY")
		for list_name, code in (
			("Call Result", "NO_ANSWER"),
			("Job Type", "PUMP_DOWN"),
			("Field Expense", "FUEL"),
			("Service Issue", "NO_WATER"),
			("Site Stage", "TESTING"),
			("System Type", "CONCRETE"),
		):
			self.assertTrue(lists.by_code(list_name, code), f"{list_name} {code}")
