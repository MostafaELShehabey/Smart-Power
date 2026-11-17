"""Who sees which customer (SP-50): featured for everyone, the rest for their owners."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power import lists
from smart_power.tests.test_shell import profile_keys
from smart_power.tests.utils import make_customer, make_user


def visible(user: str, customers: list[str]) -> set[str]:
	frappe.set_user(user)
	try:
		return set(frappe.get_list("Customer", filters={"name": ("in", customers)}, pluck="name"))
	finally:
		frappe.set_user("Administrator")


def can(user: str, customer: str, ptype: str) -> bool:
	return bool(frappe.has_permission("Customer", ptype, frappe.get_doc("Customer", customer), user=user))


class TestCustomerVisibility(IntegrationTestCase):
	def setUp(self):
		self.camelia = make_user(
			"sp.cv.camelia@example.com", ("lead_intake", "customer_followup", "followup_all")
		)
		self.owner = make_user("sp.cv.owner@example.com", ("lead_intake", "customer_followup"))
		self.colleague = make_user("sp.cv.colleague@example.com", ("lead_intake", "customer_followup"))
		self.creator = make_user("sp.cv.creator@example.com", ("quote_creator",))
		self.jaber = make_user("sp.cv.jaber@example.com", profile_keys("SP Store and Installations"))
		self.featured = make_customer("01005000501", "عميل مميز", sp_featured=1, sp_owner_user=self.owner)
		self.owned = make_customer("01005000502", "عميل له مسؤول", sp_owner_user=self.owner)
		self.fresh = make_customer("01005000503", "عميل جديد")
		self.all = [self.featured, self.owned, self.fresh]

	def test_a_featured_customer_is_seen_by_everyone_read_only(self):
		# محمد جابر (store and installations) finds a featured customer and opens it read-only
		self.assertIn(self.featured, visible(self.jaber, self.all))
		self.assertTrue(can(self.jaber, self.featured, "read"))
		self.assertFalse(can(self.jaber, self.featured, "write"))
		self.assertTrue(can(self.owner, self.featured, "write"))

	def test_a_colleagues_customer_is_hidden(self):
		self.assertNotIn(self.owned, visible(self.colleague, self.all))
		self.assertFalse(can(self.colleague, self.owned, "read"))
		self.assertIn(self.owned, visible(self.owner, self.all))

	def test_working_on_one_of_its_cases_shows_the_customer(self):
		frappe.get_doc(
			{
				"doctype": "SP Case",
				"customer": self.owned,
				"channel": "Call",
				"follow_up_owner": self.owner,
				"quote_creator": self.creator,
			}
		).insert()
		self.assertIn(self.owned, visible(self.creator, self.all))
		self.assertTrue(can(self.creator, self.owned, "read"))

	def test_a_customer_with_no_owner_and_no_case_is_seen_by_all(self):
		self.assertIn(self.fresh, visible(self.colleague, self.all))

	def test_the_follow_up_lead_and_the_admin_see_all(self):
		admin = make_user("sp.cv.admin@example.com", ("admin",))
		for user in (self.camelia, admin):
			self.assertEqual(visible(user, self.all), set(self.all), user)

	def test_saved_views(self):
		lists.seed_list_views()
		self.assertEqual([v["label"] for v in lists.views_for(self.owner)["Customer"]], ["Mine", "Featured"])
		admin = make_user("sp.cv.admin@example.com", ("admin",))
		self.assertEqual(
			[v["label"] for v in lists.views_for(admin)["Customer"]], ["Mine", "Featured", "All"]
		)
