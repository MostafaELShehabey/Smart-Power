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

	def test_pump_asks_hp_well_water_level_and_pump_depth(self):
		names = [f["fieldname"] for f in request_fields(PUMP)]
		self.assertEqual(names, ["hp", "well_depth_m", "water_level_m", "pump_depth_m"])
		self.assertEqual(request_fields(by_code("System Type", "LIGHTING")), [])

	def test_only_the_types_fields_are_kept_as_numbers(self):
		cleaned = clean_details(
			PUMP, {"hp": "20", "well_depth_m": "120", "water_level_m": 40, "pump_depth_m": 90, "kw": 9}
		)
		self.assertEqual(
			cleaned, {"hp": 20.0, "well_depth_m": 120.0, "water_level_m": 40.0, "pump_depth_m": 90.0}
		)

	def test_negative_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			clean_details(PUMP, {"hp": -5, "well_depth_m": 1, "water_level_m": 1, "pump_depth_m": 1})

	def test_pump_fields_are_required(self):
		# story: HP, well depth, water level and pump depth show and are required for pumps
		with self.assertRaises(frappe.MandatoryError):
			clean_details(PUMP, {"hp": 20, "well_depth_m": 120})

	def test_seeding_keeps_the_admins_fields(self):
		value = frappe.get_doc("SP List Value", PUMP)
		value.meta_json = json.dumps({"request_fields": [{"fieldname": "x", "fieldtype": "Data"}]})
		value.save()
		seed_request_fields()
		self.assertEqual([f["fieldname"] for f in request_fields(PUMP)], ["x"])

	def test_case_keeps_its_types_details(self):
		case = make_case(
			system_types=[{"system_type": PUMP}],
			request_details={
				"hp": 20,
				"well_depth_m": "90",
				"water_level_m": 30,
				"pump_depth_m": 60,
				"kw": 5,
			},
			site_visit_needed=1,
		)
		self.assertEqual(
			json.loads(case.request_details)
			if isinstance(case.request_details, str)
			else case.request_details,
			{"hp": 20.0, "well_depth_m": 90.0, "water_level_m": 30.0, "pump_depth_m": 60.0},
		)
		self.assertTrue(case.site_visit_needed)
