"""X13 Audit log (SP-137): a rejected payment shows with its user, time and reason; nobody deletes
or edits an audit row, the admin included."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from smart_power.sp_core import audit_trail as at
from smart_power.sp_core.services.audit import audit
from smart_power.sp_finance import transfer as tf
from smart_power.sp_finance.accounts import holder_account, seed_accounts
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule

load_erpnext_test_data()

COMPANY, PHOTO, AMOUNT = "_Test Company", "/files/sp137-deposit.jpg", 700
REASON = "الإيصال لا يطابق المبلغ"


class TestAuditTrail(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)
		cls.admin = make_user("sp.at.admin@example.com", ("admin",))
		cls.driver = make_user("sp.at.driver@example.com", ("custody_holder",))
		cls.cash = holder_account(cls.driver, "Transit", COMPANY)
		cls.post = frappe.db.get_value("Account", {"company": COMPANY, "account_name": "The Post"})

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_rule("transfer_over_balance", "Warn", warn_needs_reason=0)

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def pending_payment(self):
		doc = frappe.get_doc(
			{
				"doctype": "SP Transfer",
				"from_account": self.cash,
				"to_account": self.post,
				"amount": AMOUNT,
				"work_date": today(),
				"receipt_photo": PHOTO,
			}
		)
		return self.as_user(self.driver, lambda: (doc.insert(), doc.submit()) and doc)

	def test_a_rejected_payment_shows_reject_with_user_time_and_reason(self):
		doc = self.pending_payment()
		self.as_user(self.admin, tf.reject, doc.name, REASON)
		found = self.as_user(
			self.admin, at.rows, {"doctype": "SP Transfer", "name": doc.name, "from_date": today()}
		)
		rejected = [r for r in found if r["action"] == "Rejected"]
		self.assertEqual(len(rejected), 1)
		self.assertEqual(rejected[0]["user"], self.admin)
		self.assertTrue(rejected[0]["at"])
		self.assertIn(REASON, rejected[0]["details"])

	def test_nobody_deletes_or_edits_an_audit_row_the_admin_included(self):
		row = audit("Test action")
		for user in (self.admin, "Administrator"):
			with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
				self.as_user(user, frappe.delete_doc, "SP Audit Log", row.name)
		self.assertTrue(frappe.db.exists("SP Audit Log", row.name))
		row.action = "Something else"
		with self.assertRaises(frappe.ValidationError):
			row.save(ignore_permissions=True)

	def test_role_changes_show_and_only_the_admin_reads_the_log(self):
		# a role change is a Version of the User (Frappe writes none inside a test run)
		frappe.get_doc(
			{
				"doctype": "Version",
				"ref_doctype": "User",
				"docname": self.driver,
				"data": json.dumps({"added": [["roles", {"role": "SP Accountant"}]]}),
			}
		).insert(ignore_permissions=True)
		found = self.as_user(
			self.admin, at.rows, {"doctype": "User", "name": self.driver, "from_date": today()}
		)
		self.assertTrue(any(r["reference_name"] == self.driver and r["source"] == "Version" for r in found))
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.driver, at.rows, {})
		self.as_user(self.admin, at.export, {"from_date": today()})
		self.assertTrue(
			frappe.db.exists("SP Audit Log", {"action": "Audit log exported", "user": self.admin})
		)
