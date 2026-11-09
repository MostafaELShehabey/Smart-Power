"""X12 Company settings (SP-25)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services import company
from smart_power.tests.utils import make_user

DT = "SP Company Settings"


def save_settings(**values):
	doc = frappe.get_single(DT)
	doc.update(values)
	doc.save(ignore_version=False)  # tests skip versions unless asked
	return doc


class TestCompanySettings(IntegrationTestCase):
	def test_admin_can_edit(self):
		user = make_user("sp.x12.admin@example.com", ("admin",))
		self.assertTrue(frappe.has_permission(DT, "write", user=user))

	def test_others_are_not_permitted(self):
		user = make_user("sp.x12.followup@example.com", ("lead_intake", "customer_followup", "quote_creator"))
		self.assertFalse(frappe.has_permission(DT, "read", user=user))
		self.assertFalse(frappe.has_permission(DT, "write", user=user))

	def test_every_change_is_in_history(self):
		before = frappe.db.count("Version", {"ref_doctype": DT})
		save_settings(owner_name="محمد سليمان", legal_name_ar="سمارت باور")
		self.assertEqual(frappe.db.count("Version", {"ref_doctype": DT}), before + 1)

	def test_templates_see_a_new_logo_after_save(self):
		save_settings(logo="")
		self.assertEqual(company.company_logo(), company.FALLBACK_LOGO)
		save_settings(logo="/files/new-logo.png")
		self.assertEqual(company.company_logo(), "/files/new-logo.png")

	def test_addresses_in_order(self):
		save_settings(
			addresses=[
				{"label": "الخارجة", "address_ar": "الخارجة، الوادي الجديد", "phone": "0922000000"},
				{"label": "المنيرة", "address_ar": "المنيرة، الوادي الجديد"},
			]
		)
		self.assertEqual([a["label"] for a in company.company_addresses()], ["الخارجة", "المنيرة"])

	def test_same_address_twice_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			save_settings(
				addresses=[
					{"label": "الخارجة", "address_ar": "عنوان أ"},
					{"label": "الخارجة", "address_ar": "عنوان ب"},
				]
			)

	def test_templates_can_read_it(self):
		self.assertIn(
			"smart_power.sp_core.services.company.company_logo", frappe.get_hooks("jinja")["methods"]
		)
