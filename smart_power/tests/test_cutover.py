"""Go-live cutover (SP-163): the runbook's steps are ticked by their owners with when and by whom,
the checked steps wait for their proof, and the smoke tests run per user, as that user."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from smart_power.sp_core import cutover as cv
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"


class TestCutover(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.owner = make_user("sp.cut.owner@example.com", ("accountant",))
		cls.other = make_user("sp.cut.other@example.com", ("accountant",))
		cls.locked = make_user("sp.cut.locked@example.com", ("quote_creator",))
		frappe.db.set_value("User", cls.locked, "sp_login_locked", 1)

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.doc = frappe.get_doc({"doctype": cv.CUTOVER, "company": COMPANY}).insert()

	def step(self, key=None, text=None):
		return next(r for r in self.doc.steps if (key and r.step_key == key) or (text and text in r.step))

	def test_a_new_cutover_carries_the_runbook_and_the_rollback_plan(self):
		self.assertEqual(len(self.doc.steps), len(cv.RUNBOOK))
		self.assertEqual(getdate(self.step(text="تجميد").planned_on), getdate("2026-12-20"))
		self.assertEqual(getdate(self.step(text="بروفة").planned_on), getdate("2026-12-24"))
		self.assertEqual(getdate(self.step(text="جرد").planned_on), getdate("2026-12-29"))
		self.assertEqual(getdate(self.step(key=cv.SMOKE).planned_on), getdate("2027-01-01"))
		self.assertEqual(len(self.doc.rollback), len(cv.ROLLBACK_MODULES))
		self.assertEqual(self.doc.status, cv.PLANNED)

	def test_only_the_named_owner_ticks_and_the_tick_keeps_when_and_by_whom(self):
		row = self.step(text="إقفال أرصدة")
		row.owner_user = self.owner
		self.doc.save()
		task = frappe.db.get_value(
			"SP Task", {"reference_name": self.doc.name, "assigned_to": self.owner, "status": "Open"}
		)
		self.assertTrue(task)
		frappe.set_user(self.other)
		self.assertRaises(frappe.PermissionError, cv.tick, self.doc.name, row.name)
		frappe.set_user(self.owner)
		result = cv.tick(self.doc.name, row.name, note="أقفلت")
		frappe.set_user("Administrator")
		self.doc.reload()
		row = self.step(text="إقفال أرصدة")
		self.assertEqual((row.done, row.done_by, row.note), (1, self.owner, "أقفلت"))
		self.assertTrue(row.done_at)
		self.assertEqual(frappe.db.get_value("SP Task", task, "status"), "Done")
		self.assertEqual((result["status"], self.doc.status), (cv.IN_PROGRESS, cv.IN_PROGRESS))

	def test_a_tick_cannot_be_typed_in_by_saving_the_form(self):
		row = self.step(text="تحميل الأرصدة")
		row.done, row.done_by = 1, self.owner
		self.doc.save()
		self.doc.reload()
		self.assertFalse(self.step(text="تحميل الأرصدة").done)

	def test_the_checked_steps_wait_for_their_proof(self):
		smoke = self.step(key=cv.SMOKE)
		self.assertRaises(frappe.ValidationError, cv.tick, self.doc.name, smoke.name)  # not run yet
		with patch.object(cv, "_users", return_value=[self.owner, self.locked]):
			result = cv.run_smoke(self.doc.name)
		self.assertEqual((result["passed"], result["total"]), (1, 2))
		self.doc.reload()
		rows = {r.user: r for r in self.doc.smoke_tests}
		self.assertEqual(
			(rows[self.owner].account_ok, rows[self.owner].home_ok, rows[self.owner].action_ok), (1, 1, 1)
		)
		self.assertEqual((rows[self.locked].result, rows[self.locked].account_ok), (cv.FAIL, 0))
		self.assertRaises(frappe.ValidationError, cv.tick, self.doc.name, smoke.name)  # one failed

		january = self.step(key=cv.JANUARY_CLOSE)
		with patch.object(cv, "_month_closed", return_value=False):
			self.assertRaises(frappe.ValidationError, cv.tick, self.doc.name, january.name)
		review = self.step(key=cv.HYPERCARE_REVIEW)
		self.assertRaises(frappe.ValidationError, cv.tick, self.doc.name, review.name)  # January first
		with patch.object(cv, "_month_closed", return_value=True):
			cv.tick(self.doc.name, january.name)
		self.assertEqual(cv.start_hypercare(self.doc.name), cv.HYPERCARE_DAYS)
		self.doc.reload()
		last = sorted(self.doc.hypercare, key=lambda r: getdate(r.day))[-1]
		last.open_highest = 1
		self.doc.save()
		self.assertRaises(frappe.ValidationError, cv.tick, self.doc.name, review.name)  # a Highest is open
		last.open_highest = 0
		self.doc.save()
		cv.tick(self.doc.name, review.name)

	def test_decisions_and_backups_keep_who_and_when(self):
		cv.start_hypercare(self.doc.name)
		self.doc.reload()
		self.doc.rollback[0].decision = "Continue in the system"
		self.doc.hypercare[0].backup_verified = 1
		self.doc.save()
		self.doc.reload()
		self.assertEqual(self.doc.rollback[0].decided_by, "Administrator")
		self.assertTrue(self.doc.rollback[0].decided_at)
		self.assertEqual(self.doc.hypercare[0].backup_verified_by, "Administrator")

	def test_only_the_admin_runs_the_smoke_tests(self):
		frappe.set_user(self.owner)
		self.assertRaises(frappe.PermissionError, cv.run_smoke, self.doc.name)
		self.assertRaises(frappe.PermissionError, cv.start_hypercare, self.doc.name)
