"""Customers are numbered CUS-##### (SP-31)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.setup import apply_customer_naming


class TestCustomerNaming(IntegrationTestCase):
	def test_new_customer_gets_a_cus_number(self):
		apply_customer_naming()
		doc = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "عميل ترقيم", "sp_mobile": "01009998877"}
		).insert()
		self.assertTrue(doc.name.startswith("CUS-"), doc.name)
		self.assertEqual(frappe.db.get_single_value("Selling Settings", "cust_master_name"), "Naming Series")

	def test_series_ships_as_developer_property_setters(self):
		for prop in ("options", "default"):
			name = f"Customer-naming_series-{prop}"
			self.assertEqual(
				frappe.db.get_value("Property Setter", name, ["value", "module"]), ("CUS-.#####", "SP Sales")
			)

	def test_erpnext_test_data_keeps_its_names(self):
		# ERPNext's test records link "_Test Customer" by name, so it must not become CUS-#####.
		apply_customer_naming()
		from smart_power.tests.utils import load_erpnext_test_data

		load_erpnext_test_data()
		self.assertTrue(frappe.db.exists("Customer", "_Test Customer"))
		self.assertEqual(frappe.defaults.get_global_default("cust_master_name"), "Naming Series")
