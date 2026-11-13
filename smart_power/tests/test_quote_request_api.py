"""The quote request API behind the C3 form (SP-47)."""

import json

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.quote_request import (
	check_mobile,
	create_quote_request,
	followup_owners,
	seed_request_fields,
)
from smart_power.tests.utils import make_customer, make_user

PUMP = "System Type-PUMP"


def as_user(user, fn, *args):
	frappe.set_user(user)
	try:
		return fn(*args)
	finally:
		frappe.set_user("Administrator")


class TestQuoteRequestApi(IntegrationTestCase):
	def setUp(self):
		seed_request_fields()
		self.camelia = make_user(
			"sp.qr.camelia@example.com", ("lead_intake", "customer_followup", "followup_all")
		)
		self.maha = make_user("sp.qr.maha@example.com", ("marketing_agent", "lead_intake", "quote_creator"))
		self.gaber = make_user("sp.qr.gaber@example.com", ("main_store_keeper",))

	def request(self, **kw):
		return {
			"system_type": PUMP,
			"mobile": "+20 100 777 0001",
			"customer_name": "عميل طلب جديد",
			"tier": "Individual",
			"channel": "Call",
			"site_visit_needed": 1,
			"request_notes": "بئر على عمق كبير",
			"details": {"well_depth_m": "150", "motor_hp": 25, "roof_area_m2": 9},
			**kw,
		}

	def test_new_customer_and_case(self):
		result = as_user(self.camelia, create_quote_request, self.request())
		self.assertTrue(result["new_customer"])
		case = frappe.get_doc("SP Case", result["case"])
		self.assertEqual(
			(case.status, case.customer, case.requested_by, case.follow_up_owner, case.channel),
			("Quote request", result["customer"], self.camelia, self.camelia, "Call"),
		)
		self.assertEqual(frappe.db.get_value("Customer", result["customer"], "sp_mobile"), "01007770001")
		details = (
			json.loads(case.request_details)
			if isinstance(case.request_details, str)
			else case.request_details
		)
		self.assertEqual(details, {"well_depth_m": 150.0, "motor_hp": 25.0})
		self.assertTrue(case.site_visit_needed)

	def test_returning_customer_is_reused(self):
		existing = make_customer("01007770002", "عميل قديم")
		info = as_user(self.camelia, check_mobile, "0100 777 0002")
		self.assertEqual(
			(info["valid"], info["customer"], info["customer_name"]), (True, existing, "عميل قديم")
		)
		result = as_user(
			self.camelia, create_quote_request, self.request(mobile="01007770002", customer_name="")
		)
		self.assertEqual((result["customer"], result["new_customer"]), (existing, False))
		self.assertEqual(frappe.db.count("Customer", {"sp_mobile": "01007770002"}), 1)
		self.assertEqual(as_user(self.camelia, check_mobile, "01007770002")["open_cases"], 1)

	def test_bad_input_is_refused(self):
		with self.assertRaises(frappe.MandatoryError):
			as_user(self.camelia, create_quote_request, self.request(system_type=""))
		with self.assertRaises(frappe.ValidationError):
			as_user(self.camelia, create_quote_request, self.request(mobile="1234"))
		with self.assertRaises(frappe.MandatoryError):
			as_user(self.camelia, create_quote_request, self.request(mobile="01007770003", customer_name=" "))
		self.assertFalse(as_user(self.camelia, check_mobile, "1234")["valid"])

	def test_nothing_is_saved_when_the_case_fails(self):
		# Maha does not follow up customers, so without an owner the case is refused …
		with self.assertRaises(frappe.MandatoryError):
			as_user(self.maha, create_quote_request, self.request(mobile="01007770004"))
		# … and the new customer is not left behind
		self.assertFalse(frappe.db.exists("Customer", {"sp_mobile": "01007770004"}))

	def test_marketing_picks_the_follow_up_owner(self):
		owners = {u.name for u in as_user(self.maha, followup_owners)}
		self.assertIn(self.camelia, owners)
		result = as_user(
			self.maha,
			create_quote_request,
			self.request(mobile="01007770005", channel="Marketing", follow_up_owner=self.camelia),
		)
		self.assertEqual(frappe.db.get_value("SP Case", result["case"], "follow_up_owner"), self.camelia)

	def test_store_keeper_cannot_take_requests(self):
		with self.assertRaises(frappe.PermissionError):
			as_user(self.gaber, create_quote_request, self.request(mobile="01007770006"))
		with self.assertRaises(frappe.PermissionError):
			as_user(self.gaber, check_mobile, "01007770006")
