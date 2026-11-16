"""The task inbox (SP-39, G3): the task service, snooze, and the inbox with inline actions."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from smart_power.sp_core import inbox
from smart_power.tests.utils import make_user


class TestTaskService(IntegrationTestCase):
	def setUp(self):
		self.aya = make_user("sp.inbox.aya@example.com", ("quote_creator",))

	def test_one_open_task_per_user_and_record_and_closing_them(self):
		ref = ("User", self.aya)  # any record will do for the service
		first = inbox.create_task("Other", *ref, [self.aya, self.aya], "افحص هذا", amount=1500)
		again = inbox.create_task("Other", *ref, self.aya, "افحص هذا")
		self.assertEqual((len(first), again), (1, []))  # the open task is not given twice
		self.assertEqual(frappe.db.get_value("SP Task", first[0], "amount"), 1500)
		self.assertEqual(inbox.close_tasks(*ref, task_type="Other"), first)
		self.assertEqual(frappe.db.get_value("SP Task", first[0], "status"), "Done")

	def test_a_snoozed_task_comes_back_when_its_time_has_passed(self):
		(name,) = inbox.create_task("Other", "User", "Guest", self.aya, "لاحقًا")
		frappe.db.set_value("SP Task", name, "snoozed_until", add_to_date(now_datetime(), hours=-1))
		inbox.unsnooze()
		self.assertIsNone(frappe.db.get_value("SP Task", name, "snoozed_until"))
