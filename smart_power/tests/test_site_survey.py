"""C4 Site survey (SP-95): a request that needs a site visit gets a survey; submitting it joins
its data to the request, keeps what it replaced, closes the tasks and tells the quote creator."""

import json

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.quote_request import create_quote_request, seed_request_fields
from smart_power.sp_site import site_survey as sv
from smart_power.tests.test_quote_request_api import as_user
from smart_power.tests.utils import make_user

PUMP = "System Type-PUMP"


class TestSiteSurvey(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_request_fields()
		cls.camelia = make_user("sp.sv.camelia@example.com", ("lead_intake", "customer_followup"))
		cls.aya = make_user("sp.sv.aya@example.com", ("quote_creator",))
		cls.mostafa = make_user("sp.sv.mostafa@example.com", ("installation_manager", "site_survey"))
		cls.driver = make_user("sp.sv.driver@example.com", ("winch_operator",))

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def request(self, mobile, **details):
		values = {"hp": 20, "well_depth_m": 100, "water_level_m": 40, "pump_depth_m": 80, **details}
		case = as_user(
			self.camelia,
			create_quote_request,
			{
				"customer_name": "SP95 عميل",
				"mobile": mobile,
				"system_type": PUMP,
				"channel": "Call",
				"site_visit_needed": 1,
				"details": values,
			},
		)["case"]
		return case, frappe.db.get_value(sv.SURVEY, {"case": case})

	def test_a_request_needing_a_visit_gets_one_survey_with_a_task(self):
		case, survey = self.request("01009500951")
		doc = frappe.get_doc(sv.SURVEY, survey)
		self.assertEqual((doc.status, doc.customer_name, doc.mobile), (sv.OPEN, "SP95 عميل", "01009500951"))
		tasks = frappe.get_all(
			"SP Task",
			{"reference_name": survey, "task_type": "Site Survey", "status": "Open"},
			pluck="assigned_to",
		)
		self.assertIn(self.mostafa, tasks)
		self.assertEqual(sv.ask(frappe.get_doc(sv.CASE, case)), survey)  # asked again: the same one
		frappe.set_user(self.mostafa)  # he cannot open the case, but he has the survey
		self.assertTrue(frappe.has_permission(sv.SURVEY, "write", doc=doc))

	def test_submitting_joins_the_request_and_keeps_what_it_replaced(self):
		case, survey = self.request("01009500952")
		frappe.db.set_value(sv.CASE, case, "quote_creator", self.aya)
		frappe.set_user(self.mostafa)
		doc = frappe.get_doc(sv.SURVEY, survey)
		self.assertRaises(frappe.ValidationError, sv.complete, survey)  # nothing surveyed yet
		doc.well_depth, doc.water_level, doc.yield_m3h = 110, 60, 35
		doc.geo = '{"type":"FeatureCollection","features":[]}'
		doc.save()
		result = sv.complete(survey)
		frappe.set_user("Administrator")
		details = json.loads(frappe.db.get_value(sv.CASE, case, "request_details"))
		self.assertEqual((details["well_depth_m"], details["water_level_m"]), (110, 60))
		self.assertEqual((details["pump_depth_m"], details["hp"]), (80, 20))  # untouched
		self.assertNotIn("yield_m3h", details)  # the pump request does not ask it: it stays on the survey
		self.assertEqual(len(result["differences"]), 2)
		doc.reload()
		self.assertEqual((doc.status, doc.surveyed_by), (sv.DONE, self.mostafa))
		self.assertIn("100", doc.differences)
		self.assertTrue(
			frappe.db.exists("Comment", {"reference_name": case, "content": ("like", f"%{survey}%")})
		)
		self.assertFalse(frappe.db.exists("SP Task", {"reference_name": survey, "status": "Open"}))
		told = frappe.get_all(
			"Notification Log", {"document_name": case, "for_user": self.aya}, pluck="subject"
		)
		self.assertTrue(any("SP95" in s for s in told))
		doc.notes = "x"
		self.assertRaises(frappe.ValidationError, doc.save)  # a submitted survey no longer changes
		self.assertRaises(frappe.ValidationError, sv.complete, survey)

	def test_a_load_table_replaces_the_requests_loads(self):
		case, survey = self.request("01009500953")
		doc = frappe.get_doc(sv.SURVEY, survey)
		doc.append("loads", {"device": "ثلاجة", "qty": 2, "watts": 300, "day_hours": 6, "night_hours": 6})
		doc.save()
		sv.complete(survey)
		loads = frappe.get_doc(sv.CASE, case).loads
		self.assertEqual([(r.device, r.qty, r.watts) for r in loads], [("ثلاجة", 2, 300)])

	def test_only_a_surveyor_fills_it_and_a_status_cannot_be_typed_in(self):
		_case, survey = self.request("01009500954")
		frappe.set_user(self.driver)
		self.assertRaises(frappe.PermissionError, sv.complete, survey)
		frappe.set_user("Administrator")
		doc = frappe.get_doc(sv.SURVEY, survey)
		doc.status = sv.DONE
		doc.save()
		self.assertEqual(frappe.db.get_value(sv.SURVEY, survey, "status"), sv.OPEN)
