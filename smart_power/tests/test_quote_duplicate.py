"""Q1 "Duplicate for Customer" (SP-64): a quote's lines into a new case for another customer."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.quote_list import duplicate_for_customer
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import make_customer, make_user

PUMP = "System Type-PUMP"
PUMP_REQUEST = {"hp": 20, "well_depth_m": 120, "water_level_m": 40, "pump_depth_m": 100}


class TestQuoteDuplicate(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.aya = make_user("sp.q1d.aya@example.com", ("quote_creator",))
		cls.owner = make_user("sp.q1d.owner@example.com", ("lead_intake", "customer_followup"))
		cls.other_owner = make_user("sp.q1d.owner2@example.com", ("lead_intake", "customer_followup"))

	def source(self):
		case = case_for_test_customer(
			follow_up_owner=self.owner,
			quote_creator=self.aya,
			system_types=[{"system_type": PUMP}],
			request_details=PUMP_REQUEST,
		)
		q = quote_for(case)
		q.submit()
		return case, q

	def test_a_new_case_and_first_draft_for_the_customer(self):
		case, q = self.source()
		customer = make_customer("01009990611", "عميل منسوخ", sp_owner_user=self.other_owner)
		out = duplicate_for_customer(q.name, customer)
		new_case = frappe.get_doc("SP Case", out["case"])
		copy = frappe.get_doc("Quotation", out["quotation"])
		self.assertNotEqual(new_case.name, case.name)
		self.assertEqual(new_case.customer, customer)
		self.assertEqual(new_case.follow_up_owner, self.other_owner)  # the customer's own
		self.assertEqual([r.system_type for r in new_case.system_types], [PUMP])
		self.assertEqual(frappe.parse_json(new_case.request_details)["hp"], 20)
		self.assertEqual((copy.party_name, copy.sp_case, copy.docstatus), (customer, new_case.name, 0))
		self.assertEqual((copy.sp_version, copy.sp_root, copy.sp_previous_version), (1, copy.name, None))
		self.assertEqual((copy.sp_status, copy.sp_is_latest, copy.sp_is_approved), ("Draft", 1, 0))
		self.assertEqual(len(copy.items), len(q.items))
		self.assertEqual(copy.sp_size, "20 HP")
		# the source is untouched
		self.assertEqual(
			frappe.db.get_value("Quotation", q.name, ["sp_case", "sp_is_latest"]), (case.name, 1)
		)

	def test_needs_to_read_the_customer(self):
		_case, q = self.source()
		customer = make_customer("01009990612", "عميل زميل", sp_owner_user=self.other_owner)
		frappe.set_user(self.owner)
		try:
			with self.assertRaises(frappe.PermissionError):
				duplicate_for_customer(q.name, customer)
		finally:
			frappe.set_user("Administrator")

	def test_quote_creator_duplicates_for_a_featured_customer(self):
		_case, q = self.source()
		customer = make_customer("01009990613", "عميل مميز", sp_owner_user=self.other_owner, sp_featured=1)
		frappe.set_user(self.aya)
		try:
			out = duplicate_for_customer(q.name, customer)
		finally:
			frappe.set_user("Administrator")
		copy = frappe.get_doc("Quotation", out["quotation"])
		self.assertEqual((copy.party_name, copy.sp_quote_creator), (customer, self.aya))
