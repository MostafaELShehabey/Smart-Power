"""Mobile lookup on the quote request: new, mine, featured, colleague (SP-47)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.customer import mark_featured
from smart_power.sp_sales.quote_request import check_mobile, create_quote_request, request_reassign
from smart_power.tests.utils import make_customer, make_user


def as_user(user, fn, *args):
	frappe.set_user(user)
	try:
		return fn(*args)
	finally:
		frappe.set_user("Administrator")


class TestQuoteRequestLookup(IntegrationTestCase):
	def setUp(self):
		self.maha = make_user(
			"sp.lookup.maha@example.com", ("marketing_agent", "lead_intake", "quote_creator")
		)
		self.camelia = make_user(
			"sp.lookup.camelia@example.com", ("lead_intake", "customer_followup", "followup_all")
		)
		self.admin = make_user("sp.lookup.admin@example.com", ("admin",))
		self.maha_lead = make_customer("01007771001", "عميل مها", sp_owner_user=self.maha)

	def test_new_and_invalid(self):
		self.assertEqual(as_user(self.camelia, check_mobile, "01007771999")["status"], "new")
		self.assertEqual(as_user(self.camelia, check_mobile, "1234")["status"], "invalid")

	def test_acceptance_colleague_sees_only_the_owner(self):
		r = as_user(self.camelia, check_mobile, "0100 777 1001")
		self.assertEqual(r["status"], "colleague")
		self.assertEqual(r["owner_name"], frappe.utils.get_fullname(self.maha))
		for key in ("customer", "customer_name", "tier", "region", "open_cases"):
			self.assertFalse(r.get(key), key)

	def test_owner_sees_their_own(self):
		r = as_user(self.maha, check_mobile, "01007771001")
		self.assertEqual((r["status"], r["customer"]), ("mine", self.maha_lead))

	def test_featured_is_open_to_everyone(self):
		featured = make_customer("01007771002", "عميل مميز لمها", sp_owner_user=self.maha)
		mark_featured(featured)
		r = as_user(self.camelia, check_mobile, "01007771002")
		self.assertEqual((r["status"], r["customer"]), ("featured", featured))

	def test_colleague_customer_cannot_be_used(self):
		request = {
			"system_type": "System Type-ONGRID",
			"mobile": "01007771001",
			"channel": "Call",
			"details": {"kw": 10},
		}
		with self.assertRaises(frappe.PermissionError):
			as_user(self.camelia, create_quote_request, request)

	def test_ask_admin_to_reassign_creates_a_task(self):
		self.assertGreaterEqual(as_user(self.camelia, request_reassign, "01007771001"), 1)
		task = frappe.get_all(
			"SP Task",
			{"task_type": "Reassign Request", "reference_name": self.maha_lead, "assigned_to": self.admin},
			pluck="name",
		)
		self.assertTrue(task)
