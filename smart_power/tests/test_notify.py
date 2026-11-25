"""Notifications G4 (SP-40): the service, the event catalogue, push preferences and the feed."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power import notify
from smart_power.sp_quotes.quote_send import notify as quote_sent
from smart_power.tests.utils import make_user

PUSHED = []


def fake_push(user, event_key, subject, doctype, docname):
	PUSHED.append((user, event_key))


class TestNotify(IntegrationTestCase):
	def setUp(self):
		notify.sync_events()
		self.requester = make_user("sp.nt.requester@example.com", ("lead_intake",))
		self.camelia = make_user("sp.nt.camelia@example.com", ("customer_followup",))
		frappe.db.delete("Notification Log", {"for_user": ("in", (self.requester, self.camelia))})
		frappe.db.delete("SP User Notification Pref", {"parent": ("in", (self.requester, self.camelia))})
		PUSHED.clear()

	def tearDown(self):
		frappe.set_user("Administrator")

	def case(self):
		return frappe._dict(name="CS-TEST-NT", requested_by=self.requester, follow_up_owner=self.camelia)

	def test_a_sent_quote_tells_the_requester_and_the_follow_up_owner(self):
		quote_sent(frappe._dict(name="SAL-QTN-NT", customer_name="عميل", party_name="عميل"), self.case())
		for user in (self.requester, self.camelia):
			log = frappe.get_all(
				"Notification Log",
				{"for_user": user, "sp_event": "quote_sent"},
				["document_type", "document_name", "subject"],
			)
			self.assertEqual(len(log), 1)
			self.assertEqual((log[0].document_type, log[0].document_name), ("SP Case", "CS-TEST-NT"))
			self.assertIn("SAL-QTN-NT", log[0].subject)

	def test_push_off_for_quote_sent_gives_the_in_app_item_only(self):
		frappe.set_user(self.camelia)
		self.assertFalse(notify.set_push("quote_sent", 0))
		frappe.set_user("Administrator")
		senders = {"sp_push_senders": ["smart_power.tests.test_notify.fake_push"]}
		with patch(
			"smart_power.notify.frappe.get_hooks", side_effect=lambda name, *a, **k: senders.get(name, [])
		):
			result = notify.send(
				"quote_sent", [self.requester, self.camelia], "SP Case", "CS-TEST-NT", "Quote sent"
			)
		self.assertEqual(result["in_app"], sorted([self.requester, self.camelia]))
		self.assertEqual(result["push"], [self.requester])  # the default for quote_sent is push
		self.assertEqual(PUSHED, [(self.requester, "quote_sent")])
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": self.camelia, "sp_event": "quote_sent"})
		)

	def test_opening_one_of_three_unread_leaves_two(self):
		for i in range(3):
			notify.send("cheque_due", [self.requester], "SP Case", f"CS-{i}", f"Cheque {i} due")
		frappe.set_user(self.requester)
		data = notify.feed()
		self.assertEqual(data["unread"], 3)
		self.assertTrue(all(not item["read"] for item in data["items"][:3]))
		from frappe.desk.doctype.notification_log.notification_log import mark_as_read

		mark_as_read(data["items"][0]["name"])
		after = notify.feed()
		self.assertEqual(after["unread"], 2)
		self.assertEqual([i["read"] for i in after["items"]][-1], 1)  # unread first
		self.assertTrue(after["items"][0]["event_label"])

	def test_the_catalogue_and_my_preferences(self):
		self.assertTrue(frappe.db.exists("SP Notification Event", "installment_overdue"))
		with self.assertRaises(frappe.ValidationError):
			notify.send("no_such_event", [self.requester], None, None, "x")
		frappe.set_user(self.camelia)
		prefs = notify.preferences()
		self.assertTrue(prefs[0]["mine"])  # the events of my roles come first
		self.assertTrue(notify.set_push("discount_given", 1))
		self.assertTrue(notify.set_push("discount_given", 1))  # one row, changed in place
		self.assertEqual(
			frappe.db.count("SP User Notification Pref", {"parent": self.camelia, "event": "discount_given"}),
			1,
		)
		self.assertTrue(next(p for p in notify.preferences() if p["event"] == "discount_given")["push"])

	def test_nobody_is_notified_twice_or_as_a_guest(self):
		result = notify.send("custody", [self.requester, self.requester, None, "Guest"], None, None, "x")
		self.assertEqual(result["in_app"], [self.requester])


class TestNotifyLanguage(IntegrationTestCase):
	"""BUG-22: a daily job runs in the site's language (English here); what it writes to people
	is in each reader's own."""

	TEXT = "Instalment due: {0} from {1} (station {2}) on {3}"
	ARABIC = "قسط مستحق"

	def setUp(self):
		notify.sync_events()
		self.arabic = make_user("sp.nt.arabic@example.com", ("customer_followup",))
		self.english = make_user("sp.nt.english@example.com", ("customer_followup",))
		frappe.db.set_value("User", self.arabic, "language", "ar")
		frappe.db.set_value("User", self.english, "language", "en")
		frappe.db.delete("Notification Log", {"for_user": ("in", (self.arabic, self.english))})
		before = frappe.local.lang
		frappe.local.lang = "en"  # as a scheduled job runs
		self.addCleanup(setattr, frappe.local, "lang", before)

	def subject(self):
		return frappe._(self.TEXT).format("100", "عميل", "2026-001", "01-12-2026")

	def test_a_built_subject_is_written_in_each_readers_language(self):
		notify.send("installment_due", [self.arabic, self.english], None, None, self.subject)
		logs = dict(
			frappe.get_all(
				"Notification Log",
				{"for_user": ("in", (self.arabic, self.english))},
				["for_user", "subject"],
				as_list=True,
			)
		)
		self.assertIn(self.ARABIC, logs[self.arabic])
		self.assertTrue(logs[self.english].startswith("Instalment due"))
		self.assertEqual(frappe.local.lang, "en")  # the job's own language is left as it was

	def test_a_text_is_sent_as_it_is(self):
		notify.send("installment_due", [self.arabic], None, None, "نص جاهز")
		self.assertEqual(
			frappe.db.get_value("Notification Log", {"for_user": self.arabic}, "subject"), "نص جاهز"
		)

	def test_a_task_is_written_in_its_users_language(self):
		from smart_power.sp_core.inbox import create_task

		names = create_task("Other", None, None, [self.arabic, self.english], self.subject)
		subjects = dict(
			frappe.get_all("SP Task", {"name": ("in", names)}, ["assigned_to", "subject"], as_list=True)
		)
		self.assertIn(self.ARABIC, subjects[self.arabic])
		self.assertTrue(subjects[self.english].startswith("Instalment due"))
