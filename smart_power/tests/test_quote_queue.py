"""Q3 quote request queue (SP-48)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from smart_power.sp_sales.quote_queue import get_queue, take
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import make_user, set_setting


def as_user(user, fn, *args):
	frappe.set_user(user)
	try:
		return fn(*args)
	finally:
		frappe.set_user("Administrator")


class TestQuoteQueue(IntegrationTestCase):
	def setUp(self):
		set_setting(quote_due_hours=24, quote_amber_hours=18)
		self.aya = make_user("sp.queue.aya@example.com", ("quote_creator",))
		self.maha = make_user("sp.queue.maha@example.com", ("quote_creator", "marketing_agent"))
		self.old = make_case(system_types=[{"system_type": "System Type-PUMP"}])
		frappe.db.set_value(
			"SP Case",
			self.old.name,
			"creation",
			add_to_date(now_datetime(), hours=-20),
			update_modified=False,
		)
		self.new = make_case()

	def test_unclaimed_oldest_first_with_the_clock(self):
		rows = as_user(self.aya, get_queue, "Unclaimed")
		names = [r.name for r in rows]
		self.assertLess(names.index(self.old.name), names.index(self.new.name))
		old = next(r for r in rows if r.name == self.old.name)
		self.assertEqual(old["state"], "Amber")
		self.assertEqual(old["system_type"], "طلمبات (غاطس)")

	def test_take_moves_it_to_mine(self):
		as_user(self.aya, take, self.old.name)
		self.assertIn(self.old.name, [r.name for r in as_user(self.aya, get_queue, "Mine")])
		self.assertNotIn(self.old.name, [r.name for r in as_user(self.maha, get_queue, "Unclaimed")])
		# another quote creator no longer sees it at all (SP-35)
		self.assertNotIn(self.old.name, [r.name for r in as_user(self.maha, get_queue, "All")])

	def test_cannot_take_a_taken_request(self):
		as_user(self.aya, take, self.old.name)
		with self.assertRaises(frappe.ValidationError):
			as_user(self.aya, take, self.old.name)

	def test_sent_requests_leave_the_queue(self):
		for status in ("Draft", "Sent to customer"):
			self.new.status = status
			self.new.save()
		self.assertNotIn(self.new.name, [r.name for r in get_queue("All")])

	def test_page_roles(self):
		roles = {r.role for r in frappe.get_doc("Page", "sp-quote-queue").roles}
		self.assertEqual(roles, {"SP Quote Creator", "SP Followup All", "SP Admin", "System Manager"})
