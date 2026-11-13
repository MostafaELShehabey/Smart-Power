"""Each system type asks only its own quote request fields (SP-47)."""

import json

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services.lists import by_code
from smart_power.sp_sales.quote_request import clean_details, request_fields, seed_request_fields
from smart_power.tests.test_case import make_case

PUMP = "System Type-PUMP"


class TestRequestFields(IntegrationTestCase):
	def setUp(self):
		seed_request_fields()

	def test_pump_asks_well_and_motor(self):
		names = [f["fieldname"] for f in request_fields(PUMP)]
		self.assertEqual(names, ["well_depth_m", "head_m", "flow_m3h", "motor_hp"])
		self.assertEqual(request_fields(by_code("System Type", "LIGHTING")), [])

	def test_only_the_types_fields_are_kept_as_numbers(self):
		cleaned = clean_details(PUMP, {"well_depth_m": "120", "monthly_kwh": 900, "note": "x"})
		self.assertEqual(cleaned, {"well_depth_m": 120.0})

	def test_negative_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			clean_details(PUMP, {"head_m": -5})

	def test_required_when_the_admin_says_so(self):
		value = frappe.get_doc("SP List Value", PUMP)
		meta = json.loads(value.meta_json) if isinstance(value.meta_json, str) else value.meta_json
		meta["request_fields"][0]["reqd"] = 1
		value.meta_json = json.dumps(meta, ensure_ascii=False)
		value.save()
		with self.assertRaises(frappe.MandatoryError):
			clean_details(PUMP, {"head_m": 40})

	def test_seeding_keeps_the_admins_fields(self):
		value = frappe.get_doc("SP List Value", PUMP)
		value.meta_json = json.dumps({"request_fields": [{"fieldname": "x", "fieldtype": "Data"}]})
		value.save()
		seed_request_fields()
		self.assertEqual([f["fieldname"] for f in request_fields(PUMP)], ["x"])

	def test_case_keeps_its_types_details(self):
		case = make_case(
			system_types=[{"system_type": PUMP}],
			request_details={"well_depth_m": "90", "roof_area_m2": 50},
			site_visit_needed=1,
		)
		self.assertEqual(
			json.loads(case.request_details)
			if isinstance(case.request_details, str)
			else case.request_details,
			{"well_depth_m": 90.0},
		)
		self.assertTrue(case.site_visit_needed)
