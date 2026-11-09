"""Append-only logs, edit reasons and the task inbox permissions."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services.audit import audit, log_edit
from smart_power.tests.utils import make_user


class TestLogs(IntegrationTestCase):
	def test_audit_log_is_append_only(self):
		row = audit("settings.changed", "Smart Power Settings", "Smart Power Settings", field="validity_days")
		self.assertIn("validity_days", row.details)
		row.action = "something else"
		with self.assertRaises(frappe.ValidationError):
			row.save(ignore_permissions=True)

	def test_edit_needs_a_reason(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "x"}).insert()
		with self.assertRaises(frappe.ValidationError):
			log_edit(todo, "description", "x", "y", "  ")
		row = log_edit(todo, "description", "x", "y", "typo")
		self.assertEqual((row.old_value, row.new_value, row.reason), ("x", "y", "typo"))


class TestTaskInbox(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.a = make_user("sp.task.a@example.com", ("customer_followup",))
		cls.b = make_user("sp.task.b@example.com", ("customer_followup",))

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_users_see_only_their_tasks(self):
		mine = frappe.get_doc({"doctype": "SP Task", "subject": "call back", "assigned_to": self.a}).insert()
		other = frappe.get_doc({"doctype": "SP Task", "subject": "not yours", "assigned_to": self.b}).insert()
		frappe.set_user(self.a)
		visible = set(frappe.get_list("SP Task", pluck="name"))
		self.assertIn(mine.name, visible)
		self.assertNotIn(other.name, visible)
		self.assertFalse(frappe.has_permission("SP Task", doc=other.name))

	def test_done_records_who_and_when(self):
		task = frappe.get_doc({"doctype": "SP Task", "subject": "x", "assigned_to": self.a}).insert()
		task.status = "Done"
		task.save()
		self.assertEqual(task.completed_by, "Administrator")
		self.assertTrue(task.completed_on)
