"""Who sees a case (SP-35 rules for SP-46)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.tests.test_case import make_case
from smart_power.tests.utils import make_user


def visible(user):
	frappe.set_user(user)
	try:
		return set(frappe.get_list("SP Case", pluck="name", limit_page_length=0))
	finally:
		frappe.set_user("Administrator")


class TestCaseVisibility(IntegrationTestCase):
	def setUp(self):
		self.hussein = make_user("sp.vis.hussein@example.com", ("lead_intake", "customer_followup"))
		self.camelia = make_user(
			"sp.vis.camelia@example.com", ("lead_intake", "customer_followup", "followup_all")
		)
		self.aya = make_user("sp.vis.aya@example.com", ("quote_creator",))
		self.amira = make_user("sp.vis.amira@example.com", ("quote_creator",))
		self.gaber = make_user("sp.vis.gaber@example.com", ("main_store_keeper",))
		self.hussein_case = make_case(follow_up_owner=self.hussein, requested_by=self.hussein)
		self.camelia_case = make_case(follow_up_owner=self.camelia, requested_by=self.camelia)
		self.aya_case = make_case(
			follow_up_owner=self.camelia, requested_by=self.camelia, quote_creator=self.aya
		)
		self.aya_case.status = "Draft"
		self.aya_case.save()

	def test_follow_up_owner_sees_only_own_cases(self):
		seen = visible(self.hussein)
		self.assertIn(self.hussein_case.name, seen)
		self.assertNotIn(self.camelia_case.name, seen)
		self.assertFalse(frappe.has_permission("SP Case", "read", self.camelia_case.name, user=self.hussein))

	def test_camelia_sees_all(self):
		self.assertTrue(
			{self.hussein_case.name, self.camelia_case.name, self.aya_case.name} <= visible(self.camelia)
		)

	def test_quote_creator_sees_own_and_unclaimed_requests(self):
		seen = visible(self.aya)
		self.assertIn(self.aya_case.name, seen)  # hers
		self.assertIn(self.hussein_case.name, seen)  # an open request nobody has taken
		seen_by_amira = visible(self.amira)
		self.assertNotIn(self.aya_case.name, seen_by_amira)  # taken by آية
		self.assertIn(self.camelia_case.name, seen_by_amira)

	def test_others_see_nothing(self):
		self.assertFalse(frappe.has_permission("SP Case", "read", user=self.gaber))

	def test_camelia_profile_has_followup_all(self):
		roles = {r.role for r in frappe.get_doc("Role Profile", "SP Call Center").roles}
		self.assertIn("SP Followup All", roles)
