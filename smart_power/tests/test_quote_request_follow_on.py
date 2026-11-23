"""After a quote request is saved: alerts, tasks and marketing rules (SP-47)."""

import base64

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.quote_request import create_quote_request
from smart_power.tests.test_quote_request_api import as_user, lead_source
from smart_power.tests.utils import make_user


def request(**kw):
	return {
		"system_type": "System Type-ONGRID",
		"customer_name": "عميل متابعة",
		"channel": "Call",
		"details": {"kw": 10},
		**kw,
	}


class TestQuoteRequestFollowOn(IntegrationTestCase):
	def setUp(self):
		self.camelia = make_user(
			"sp.fo.camelia@example.com", ("lead_intake", "customer_followup", "followup_all")
		)
		self.maha = make_user("sp.fo.maha@example.com", ("marketing_agent", "lead_intake", "quote_creator"))
		self.aya = make_user("sp.fo.aya@example.com", ("quote_creator",))
		self.admin = make_user("sp.fo.admin@example.com", ("admin",))
		self.mostafa = make_user("sp.fo.mostafa@example.com", ("installation_manager",))

	def test_admins_and_quote_creators_are_told_and_get_pool_tasks(self):
		case = as_user(self.camelia, create_quote_request, request(mobile="01007772001"))["case"]
		alerted = set(frappe.get_all("Notification Log", {"document_name": case}, pluck="for_user"))
		self.assertTrue({self.admin, self.aya, self.maha} <= alerted)
		tasks = frappe.get_all(
			"SP Task", {"reference_name": case, "task_type": "Quote Request"}, pluck="assigned_to"
		)
		self.assertTrue({self.aya, self.maha} <= set(tasks))
		self.assertFalse(frappe.db.exists("SP Site Survey", {"case": case}))

	def test_site_visit_asks_installations(self):
		case = as_user(
			self.camelia, create_quote_request, request(mobile="01007772002", site_visit_needed=1)
		)["case"]
		survey = frappe.get_all(
			"SP Task",
			{
				"reference_name": frappe.db.get_value("SP Site Survey", {"case": case}),
				"task_type": "Site Survey",
			},
			pluck="assigned_to",
		)
		self.assertIn(self.mostafa, survey)

	def test_marketing_needs_a_source_and_defaults_to_camelia(self):
		with self.assertRaises(frappe.MandatoryError):
			as_user(self.maha, create_quote_request, request(mobile="01007772003", channel="Marketing"))
		case = as_user(
			self.maha,
			create_quote_request,
			request(mobile="01007772004", channel="Marketing", source=lead_source("FB_FO")),
		)["case"]
		self.assertEqual(
			frappe.db.get_value("SP Case", case, ["follow_up_owner", "source"]),
			(self.camelia, "Lead Source-FB_FO"),
		)

	def test_source_must_come_from_the_lead_source_list(self):
		with self.assertRaises(frappe.ValidationError):
			as_user(
				self.maha,
				create_quote_request,
				request(mobile="01007772005", channel="Marketing", source="System Type-PUMP"),
			)


PNG = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def upload(user, name, content=PNG):
	frappe.set_user(user)
	try:
		return (
			frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 1})
			.insert()
			.name
		)
	finally:
		frappe.set_user("Administrator")


class TestQuoteRequestPhotos(IntegrationTestCase):
	def setUp(self):
		self.camelia = make_user("sp.ph.camelia@example.com", ("lead_intake", "customer_followup"))
		self.maha = make_user("sp.ph.maha@example.com", ("lead_intake", "customer_followup"))

	def test_photos_are_attached_to_the_case(self):
		photos = [upload(self.camelia, "well.png"), upload(self.camelia, "panel.png")]
		case = as_user(self.camelia, create_quote_request, request(mobile="01007772101", photos=photos))[
			"case"
		]
		self.assertEqual(
			set(
				frappe.get_all(
					"File", {"attached_to_doctype": "SP Case", "attached_to_name": case}, pluck="name"
				)
			),
			set(photos),
		)

	def test_only_my_own_photos(self):
		theirs = upload(self.maha, "theirs.png")
		with self.assertRaises(frappe.ValidationError):
			as_user(self.camelia, create_quote_request, request(mobile="01007772102", photos=[theirs]))
		self.assertFalse(frappe.db.exists("Customer", {"sp_mobile": "01007772102"}))

	def test_only_images(self):
		doc = upload(self.camelia, "notes.txt", b"hello")
		with self.assertRaises(frappe.ValidationError):
			as_user(self.camelia, create_quote_request, request(mobile="01007772103", photos=[doc]))
