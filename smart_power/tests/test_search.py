"""Global search (SP-41): one searchable spelling, then the permission-aware search."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.search_key import normalize
from smart_power.tests.utils import load_erpnext_test_data, make_customer

load_erpnext_test_data()


class TestSearchKey(IntegrationTestCase):
	def test_arabic_written_several_ways_is_one_spelling(self):
		self.assertEqual(normalize("أحمد"), normalize("احمد"))
		self.assertEqual(normalize("إسلام"), normalize("اسلام"))
		self.assertEqual(normalize("فاطمة"), normalize("فاطمه"))
		self.assertEqual(normalize("مصطفى"), normalize("مصطفي"))
		self.assertEqual(normalize("مُحَمَّد"), normalize("محمد"))  # diacritics
		self.assertEqual(normalize("محـــمد"), normalize("محمد"))  # tatweel
		self.assertEqual(normalize("  Smart   POWER "), "smart power")

	def test_a_customer_keeps_its_search_key(self):
		name = make_customer("01007770001", "أحمد عبد الرحمن")
		key = frappe.db.get_value("Customer", name, "sp_search_key")
		self.assertIn("احمد عبد الرحمن", key)
		self.assertIn("01007770001", key)
