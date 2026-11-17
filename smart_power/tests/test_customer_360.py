"""C2 customer record (SP-50): the customer's cases, quotes, calls, stations and documents."""

import json

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.customer_360 import customer_360
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_shell import profile_keys
from smart_power.tests.utils import load_erpnext_test_data, make_customer, make_quotation, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"


def as_user(user, fn, *args):
	frappe.set_user(user)
	try:
		return fn(*args)
	finally:
		frappe.set_user("Administrator")


class TestCustomer360(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		self.owner = make_user("sp.c360.owner@example.com", ("lead_intake", "customer_followup"))
		self.jaber = make_user("sp.c360.jaber@example.com", profile_keys("SP Store and Installations"))
		self.colleague = make_user("sp.c360.colleague@example.com", ("lead_intake", "customer_followup"))
		self.customer = make_customer("01005003601", "عميل ثلاثمائة وستين", sp_owner_user=self.owner)
		self.case = frappe.get_doc(
			{
				"doctype": "SP Case",
				"customer": self.customer,
				"channel": "Call",
				"follow_up_owner": self.owner,
				"system_types": [{"system_type": "System Type-PUMP"}],
			}
		).insert()

	def test_three_quote_versions_with_status_and_sale_total_only(self):
		case = frappe.get_doc(
			{
				"doctype": "SP Case",
				"customer": "_Test Customer",
				"channel": "Call",
				"follow_up_owner": self.owner,
			}
		).insert()
		for _ in range(3):
			make_quotation(case=case.name)  # quotes are for ERPNext's test customer
		view = customer_360("_Test Customer")
		quotes = [q for q in view["quotes"] if q.sp_case == case.name]
		self.assertEqual(len(quotes), 3)
		self.assertEqual(sorted(q.sp_version for q in quotes), [1, 2, 3])
		self.assertTrue(all(q.sp_status and q.grand_total for q in quotes))
		self.assertNotIn("cost", json.dumps(view, default=str).lower())

	def test_a_featured_customer_with_two_stations_read_only(self):
		frappe.db.set_value("Customer", self.customer, "sp_featured", 1)
		for _ in range(2):
			frappe.get_doc({"doctype": "SP Station", "customer": self.customer, "company": COMPANY}).insert()
		view = as_user(self.jaber, customer_360, self.customer)
		self.assertEqual(len(view["stations"]), 2)
		self.assertFalse(view["can_edit"])
		self.assertFalse(view["can_log_call"])

	def test_log_call_is_on_the_active_case_for_its_owner(self):
		view = as_user(self.owner, customer_360, self.customer)
		self.assertEqual(view["active_case"], self.case.name)
		self.assertTrue(view["can_log_call"])
		self.assertTrue(view["can_request"])

	def test_calls_and_documents(self):
		frappe.get_doc(
			{"doctype": "SP Call Log", "case": self.case.name, "result": "Call Result-NO_ANSWER"}
		).insert()
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "sp-c360.txt",
				"content": "مستند",
				"attached_to_doctype": "SP Case",
				"attached_to_name": self.case.name,
				"is_private": 1,
			}
		).insert()
		view = customer_360(self.customer)
		self.assertEqual([c.case for c in view["calls"]], [self.case.name])
		self.assertIn("sp-c360.txt", [f.file_name for f in view["documents"]])

	def test_a_colleague_cannot_open_it(self):
		with self.assertRaises(frappe.PermissionError):
			as_user(self.colleague, customer_360, self.customer)
