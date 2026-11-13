"""Owner changes on a case go through Reassign, with a reason and a history row (SP-46)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.case import reassign
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import make_user


class TestCaseReassign(IntegrationTestCase):
	def setUp(self):
		self.admin = make_user("sp.case.admin@example.com", ("admin",))
		self.camelia = make_user("sp.case.camelia@example.com", ("lead_intake", "customer_followup"))

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_admin_reassigns_with_a_reason(self):
		case = make_case()
		old = case.follow_up_owner
		frappe.set_user(self.admin)
		reassign(case.name, "follow_up_owner", self.camelia, "الإجازة")
		frappe.set_user("Administrator")
		row = frappe.get_doc("SP Case", case.name).owner_history[-1]
		self.assertEqual(
			(row.role_kind, row.from_user, row.to_user, row.reason, row.changed_by),
			("Follow-up Owner", old, self.camelia, "الإجازة", self.admin),
		)
		self.assertTrue(row.from_date)

	def test_direct_change_is_refused(self):
		case = make_case()
		case.follow_up_owner = self.camelia
		with self.assertRaises(frappe.ValidationError):
			case.save()

	def test_reason_is_required(self):
		case = make_case()
		with self.assertRaises(frappe.MandatoryError):
			reassign(case.name, "follow_up_owner", self.camelia, "  ")

	def test_only_the_admin_reassigns(self):
		case = make_case()
		frappe.set_user(self.camelia)
		with self.assertRaises(frappe.PermissionError):
			reassign(case.name, "follow_up_owner", self.camelia, "سبب")

	def test_follow_up_owner_cannot_be_removed(self):
		case = make_case()
		with self.assertRaises(frappe.MandatoryError):
			reassign(case.name, "follow_up_owner", None, "سبب")

	def test_quote_creator_can_be_set_later(self):
		creator = make_user("sp.case.aya@example.com", ("quote_creator",))
		case = make_case()
		reassign(case.name, "quote_creator", creator, "استلام الطلب")
		self.assertEqual(frappe.db.get_value("SP Case", case.name, "quote_creator"), creator)
