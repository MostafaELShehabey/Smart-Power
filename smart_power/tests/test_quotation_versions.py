"""Quote versions and the approved version (SP-54)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services.lists import by_code
from smart_power.sp_sales.quotation import approve_version, new_version
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import make_user


def submitted(q):
	q.submit()
	return q


class TestQuotationVersions(IntegrationTestCase):
	def setUp(self):
		self.owner = make_user("sp.ver.owner@example.com", ("lead_intake", "customer_followup"))
		self.other = make_user("sp.ver.other@example.com", ("lead_intake", "customer_followup"))
		self.case = case_for_test_customer(follow_up_owner=self.owner)

	def test_versions_are_numbered_per_case(self):
		v1 = quote_for(self.case)
		v2 = frappe.get_doc("Quotation", new_version(v1.name))
		self.assertEqual((v1.sp_version, v2.sp_version), (1, 2))
		self.assertEqual((v2.sp_previous_version, v2.sp_case, v2.docstatus), (v1.name, self.case.name, 0))
		self.assertEqual(len(v2.items), len(v1.items))
		other_case = case_for_test_customer()
		self.assertEqual(quote_for(other_case).sp_version, 1)

	def test_approve_marks_one_version_and_the_case(self):
		v1 = submitted(quote_for(self.case))
		v2 = submitted(frappe.get_doc("Quotation", new_version(v1.name)))
		approve_version(v1.name)
		approve_version(v2.name)
		self.assertEqual(frappe.db.get_value("SP Case", self.case.name, "accepted_quotation"), v2.name)
		self.assertEqual(
			(
				frappe.db.get_value("Quotation", v1.name, "sp_is_approved"),
				frappe.db.get_value("Quotation", v2.name, "sp_is_approved"),
			),
			(0, 1),
		)

	def test_draft_cannot_be_approved(self):
		with self.assertRaises(frappe.ValidationError):
			approve_version(quote_for(self.case).name)

	def test_only_owner_creator_or_admin_approve(self):
		q = submitted(quote_for(self.case))
		frappe.set_user(self.other)
		try:
			with self.assertRaises(frappe.PermissionError):
				approve_version(q.name)
		finally:
			frappe.set_user("Administrator")
		frappe.set_user(self.owner)
		try:
			approve_version(q.name)
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(frappe.db.get_value("Quotation", q.name, "sp_is_approved"))

	def test_closed_case_keeps_its_version(self):
		q = submitted(quote_for(self.case))
		self.case.reload()
		self.case.status = "Lost"
		self.case.lost_reason = by_code("Lost Reason", "PRICE_CHECK_ONLY")
		self.case.save()
		with self.assertRaises(frappe.ValidationError):
			approve_version(q.name)

	def test_a_sent_version_cannot_be_cancelled(self):
		q = submitted(quote_for(self.case))
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Quotation", q.name).cancel()
