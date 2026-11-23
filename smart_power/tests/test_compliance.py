"""Qualification and compliance (RG1, SP-101): the expiry reminders go out once per mark, the home
card counts what is expiring, and a period's report takes the installed capacity statement."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from smart_power.dashboards import cards
from smart_power.sp_stations import compliance as c
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

MONTH, WEEK, FAR = 30, 7, 90  # days to expiry: the story's 30-day mark, the 7-day mark, no mark yet
H1 = ("2027-01-01", "2027-06-30")  # the story's H1-2027


def document(days: int | None, **values):
	doc = frappe.new_doc(c.DOCUMENT)
	doc.update({"doc_type": "Qualification Certificate", "number": f"SP101-{days}", **values})
	if days is not None:
		doc.expiry_date = add_days(nowdate(), days)
	return doc.insert(ignore_permissions=True)


class TestCompliance(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.officer = make_user("sp101-officer@example.com", ("regulatory_compliance",))
		cls.admin = make_user("sp101-admin@example.com", extra_roles=("SP Admin",))
		frappe.db.set_value("User", cls.officer, "language", "ar")
		frappe.db.set_value("User", cls.admin, "language", "en")
		cls.accountant = make_user("sp101-accountant@example.com", ("accountant",))

	def tearDown(self):
		frappe.set_user("Administrator")

	def alerts(self, doc, user) -> int:
		return frappe.db.count("Notification Log", {"for_user": user, "document_name": doc.name})

	def test_a_mark_reminds_the_officer_and_the_admin_once(self):
		doc, far = document(MONTH), document(FAR)
		self.assertEqual((doc.status, far.status, doc.reminder_days), (c.EXPIRING, c.VALID, c.DEFAULT_MARKS))
		c.expiry_reminders()
		c.expiry_reminders()
		self.assertEqual((self.alerts(doc, self.officer), self.alerts(doc, self.admin)), (1, 1))
		# each reader gets it in their own language, whatever language the job runs in
		subject = {"document_name": doc.name}
		arabic = frappe.db.get_value("Notification Log", {**subject, "for_user": self.officer}, "subject")
		english = frappe.db.get_value("Notification Log", {**subject, "for_user": self.admin}, "subject")
		self.assertIn("شهادة التأهيل", arabic)
		self.assertIn("Qualification Certificate", english)
		self.assertEqual(self.alerts(doc, self.accountant) + self.alerts(far, self.officer), 0)
		# the next mark, and a day the job missed after it: one more alert
		c.expiry_reminders(add_days(nowdate(), MONTH - WEEK + 1))
		c.expiry_reminders(add_days(nowdate(), MONTH - WEEK + 2))
		self.assertEqual(self.alerts(doc, self.officer), 2)
		# past the expiry date the status follows, with no further mark to send
		c.expiry_reminders(add_days(nowdate(), MONTH + 1))
		self.assertEqual(frappe.db.get_value(c.DOCUMENT, doc.name, "status"), c.EXPIRED)
		self.assertEqual(self.alerts(doc, self.officer), 2)

	def test_a_renewed_document_starts_its_marks_again(self):
		doc = document(WEEK)
		c.expiry_reminders()
		doc.reload()
		doc.expiry_date = add_days(nowdate(), FAR)
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.status, c.VALID)
		c.expiry_reminders()
		self.assertEqual(self.alerts(doc, self.officer), 1)
		c.expiry_reminders(add_days(nowdate(), FAR - MONTH))
		self.assertEqual(self.alerts(doc, self.officer), 2)

	def test_the_dates_and_reminder_days_are_checked(self):
		self.assertRaises(frappe.ValidationError, document, MONTH, reminder_days="soon")
		self.assertRaises(frappe.ValidationError, document, MONTH, reminder_days="30,0")
		self.assertRaises(frappe.ValidationError, document, MONTH, issue_date=add_days(nowdate(), FAR))
		self.assertEqual(document(MONTH, reminder_days="7, 45,7").reminder_days, "45,7")
		self.assertEqual(document(None).status, c.VALID)

	def test_the_home_card_counts_what_is_expiring(self):
		self.assertIn("compliance", cards.variants_of(self.officer))
		self.assertNotIn("compliance", cards.variants_of(self.accountant))
		before = cards.documents_expiring(self.officer)["value"]
		document(MONTH), document(FAR), document(-1)
		card = cards.documents_expiring(self.officer)
		self.assertEqual((card["value"] - before, card["indicator"]), (2, cards.RED))

	def test_a_report_takes_the_statement_of_its_period(self):
		frappe.set_user(self.officer)
		report = frappe.get_doc({"doctype": c.REPORT, "period_from": H1[0], "period_to": H1[1]}).insert()
		c.attach_statement(report.name)
		result = c.attach_statement(report.name)  # attached again: the earlier file is replaced
		report.reload()
		attached = {"attached_to_doctype": c.REPORT, "attached_to_name": report.name}
		self.assertEqual(frappe.db.count("File", attached), 1)
		file = frappe.get_doc("File", attached)
		self.addCleanup(lambda: frappe.delete_doc("File", file.name, force=True, ignore_permissions=True))
		self.assertEqual((report.file, result["file"]), (file.file_url, file.file_url))
		self.assertTrue(file.is_private and file.file_name.endswith(".xlsx"))
		snapshot = json.loads(report.r3_snapshot)
		self.assertEqual(snapshot["filters"], {"from_date": H1[0], "to_date": H1[1]})
		self.assertTrue(snapshot["rows"][-1]["is_total"])
		report.status = c.SUBMITTED
		report.save()
		self.assertEqual(str(report.submitted_on), nowdate())
		self.assertRaises(frappe.ValidationError, c.attach_statement, report.name)
		frappe.set_user(self.accountant)
		self.assertRaises(frappe.PermissionError, c.attach_statement, report.name)

	def test_a_period_ends_after_it_starts(self):
		report = frappe.get_doc({"doctype": c.REPORT, "period_from": H1[1], "period_to": H1[0]})
		self.assertRaises(frappe.ValidationError, report.insert, ignore_permissions=True)
