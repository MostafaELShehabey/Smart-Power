"""User guides and training (SP-162): a guide per person profile, seen by its own people, printed
as a one-page card; a session completes a user who did the top three tasks unaided."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core import guides as gd
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

CALL_CENTER, STORE = "SP Call Center", "SP Store and Installations"


class TestUserGuides(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		gd.seed_guides()
		cls.caller = make_user(
			"sp.guide.caller@example.com", ("lead_intake", "customer_followup", "followup_all")
		)
		cls.keeper = make_user(
			"sp.guide.keeper@example.com", ("main_store_keeper", "installation_technician")
		)
		cls.partial = make_user("sp.guide.partial@example.com", ("lead_intake",))

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_every_profile_has_a_seeded_guide_and_an_edit_is_kept(self):
		self.assertEqual(set(frappe.get_all(gd.GUIDE, pluck="name")) >= set(gd._profiles()), True)
		guide = frappe.get_doc(gd.GUIDE, CALL_CENTER)
		self.assertEqual(len([t for t in guide.tasks if t.is_top]), gd.TOP_TASKS)
		guide.title = "دليل معدّل"
		guide.save()
		self.assertEqual(gd.seed_guides(), 0)  # what a migrate runs
		self.assertEqual(frappe.db.get_value(gd.GUIDE, CALL_CENTER, "title"), "دليل معدّل")

	def test_a_user_sees_only_the_guides_of_their_profile(self):
		self.assertEqual(gd.guides_for(self.caller), [CALL_CENTER])
		self.assertEqual(gd.guides_for(self.partial), [])  # one role of the profile is not the profile
		frappe.set_user(self.caller)
		self.assertEqual([g["name"] for g in gd.my_guides()], [CALL_CENTER])
		self.assertEqual(frappe.get_list(gd.GUIDE, pluck="name"), [CALL_CENTER])
		self.assertFalse(frappe.has_permission(gd.GUIDE, "read", doc=frappe.get_doc(gd.GUIDE, STORE)))
		self.assertTrue(frappe.has_permission(gd.GUIDE, "read", doc=frappe.get_doc(gd.GUIDE, CALL_CENTER)))
		frappe.set_user("Administrator")
		self.assertTrue(set(gd._profiles()) <= set(gd.guides_for("Administrator")))

	def test_a_guide_keeps_three_top_tasks_and_a_real_profile(self):
		guide = frappe.get_doc(gd.GUIDE, STORE)
		guide.append("tasks", {"task": "رابعة", "is_top": 1})
		self.assertRaises(frappe.ValidationError, guide.save)
		self.assertRaises(
			frappe.ValidationError,
			frappe.get_doc({"doctype": gd.GUIDE, "title": "x", "profile": "No Such Profile"}).insert,
		)

	def test_the_card_prints_the_top_tasks(self):
		html = frappe.get_print(gd.GUIDE, STORE, print_format="SP Quick Reference Card")
		guide = frappe.get_doc(gd.GUIDE, STORE)
		top = next(t for t in guide.tasks if t.is_top)
		self.assertIn(guide.title, html)
		self.assertIn(top.task, html)


class TestTraining(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		gd.seed_guides()
		cls.keeper = make_user(
			"sp.train.keeper@example.com", ("main_store_keeper", "installation_technician")
		)
		cls.late = make_user("sp.train.late@example.com", ("main_store_keeper", "installation_technician"))

	def setUp(self):
		frappe.set_user("Administrator")

	def session(self, rows):
		return frappe.get_doc(
			{"doctype": gd.SESSION, "session_date": "2026-12-26", "guide": STORE, "attendees": rows}
		).insert()

	def test_a_user_completes_when_they_did_the_top_three_unaided(self):
		doc = self.session(
			[
				{"user": self.keeper, "attended": 1, "task_1": 1, "task_2": 1, "task_3": 1},
				{"user": self.late, "attended": 1, "task_1": 1, "task_2": 1},
			]
		)
		guide = frappe.get_doc(gd.GUIDE, STORE)
		self.assertEqual(doc.top_task_1, next(t.task for t in guide.tasks if t.is_top))
		done = {r.user: r for r in doc.attendees}
		self.assertEqual((done[self.keeper].completed, done[self.keeper].observed_by), (1, "Administrator"))
		self.assertTrue(done[self.keeper].observed_on)
		self.assertEqual((done[self.late].completed, done[self.late].observed_by), (0, None))
		self.assertEqual(doc.completed_count, 1)

		_columns, data = gd.training_report({})
		rows = {r["user"]: r for r in data}
		self.assertEqual((rows[self.keeper]["completed"], rows[self.keeper]["session"]), (1, doc.name))
		self.assertEqual((rows[self.late]["attended"], rows[self.late]["completed"]), (1, 0))
		self.assertEqual(rows[self.keeper]["guides"], frappe.db.get_value(gd.GUIDE, STORE, "title"))
		open_rows = {r["user"] for r in gd.training_report({"only_open": 1})[1]}
		self.assertIn(self.late, open_rows)
		self.assertNotIn(self.keeper, open_rows)

	def test_a_user_is_listed_once_per_session(self):
		self.assertRaises(
			frappe.ValidationError, self.session, [{"user": self.keeper}, {"user": self.keeper}]
		)

	def test_only_the_admin_reads_the_status(self):
		frappe.set_user(self.keeper)
		self.assertRaises(frappe.PermissionError, gd.training_report, {})
		frappe.set_user("Administrator")
