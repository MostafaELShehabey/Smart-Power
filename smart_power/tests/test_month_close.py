"""A14 Month close (SP-126): the checklist shows what is still open in the month; a closed month
refuses every entry dated in it, for the admin too, until it is reopened with a reason."""

import frappe
from erpnext.accounts.doctype.accounting_period.accounting_period import ClosedAccountingPeriod
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, get_first_day, today

from smart_power.sp_finance import month_close as mc
from smart_power.sp_finance.accounts import holder_account, seed_accounts
from smart_power.tests.test_transit import journal
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule

load_erpnext_test_data()

COMPANY, PHOTO, AMOUNT = "_Test Company", "/files/sp126-deposit.jpg", 500
MIDDLE = 14  # sp-allow-number: days after the 1st, the story's 15th


class MonthCase(IntegrationTestCase):
	"""Each scenario is its own class: the class shares one transaction."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)
		cls.admin = make_user("sp.mc.admin@example.com", ("admin",))
		cls.driver = make_user("sp.mc.driver@example.com", ("custody_holder",))
		cls.month = get_first_day(add_months(today(), -2))
		cls.day = add_days(cls.month, MIDDLE)
		acc = lambda n: frappe.db.get_value("Account", {"company": COMPANY, "account_name": n})  # noqa: E731
		cls.post, cls.bank = acc("The Post"), acc("Smart Power Bank Misr")
		cls.cash = holder_account(cls.driver, "Transit", COMPANY)

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_rule("transfer_over_balance", "Warn", warn_needs_reason=0)

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def pending_deposit(self, day=None):
		doc = frappe.get_doc(
			{
				"doctype": "SP Transfer",
				"from_account": self.cash,
				"to_account": self.post,
				"amount": AMOUNT,
				"work_date": day or self.day,
				"receipt_photo": PHOTO,
			}
		)
		return self.as_user(self.driver, lambda: (doc.insert(), doc.submit()) and doc)

	def checks(self):
		data = self.as_user(self.admin, mc.checklist, str(self.month), COMPANY)
		return {c["key"]: c for c in data["checks"]}

	def close(self):
		reasons = {k: "checked by hand" for k, c in self.checks().items() if c["status"] == mc.RED}
		return self.as_user(self.admin, mc.close_month, str(self.month), COMPANY, reasons)


class TestPendingConfirmations(MonthCase):
	def test_two_pending_payments_in_the_month_turn_confirmations_red_with_a_link(self):
		first, second = self.pending_deposit(), self.pending_deposit()
		row = self.checks()["confirmations"]
		self.assertEqual((row["status"], row["count"]), (mc.RED, 2))
		self.assertIn(first.name, row["details"])
		self.assertIn(second.name, row["details"])
		self.assertEqual(row["route"]["route"], ["sp-confirmations"])
		self.assertEqual(row["route"]["options"]["from_date"], str(self.month))
		self.assertEqual(self.checks()["commission"]["status"], mc.RED)  # no R5 sheet for the month (SP-143)


class TestClosedMonth(MonthCase):
	def test_a_closed_month_refuses_a_journal_dated_in_it_even_for_the_admin_until_reopened(self):
		self.pending_deposit()
		with self.assertRaises(frappe.MandatoryError):  # a red check needs its reason
			self.as_user(self.admin, mc.close_month, str(self.month), COMPANY, {})
		name = self.close()
		doc = frappe.get_doc(mc.CLOSE, name)
		self.assertEqual(doc.status, mc.CLOSED)
		self.assertEqual(
			next(c for c in doc.checks if c.key == "confirmations").override_reason, "checked by hand"
		)
		self.assertTrue(mc.is_closed(COMPANY, self.day))
		with self.assertRaises(ClosedAccountingPeriod):  # as Administrator
			journal(self.post, self.bank, AMOUNT, self.day)
		with self.assertRaises(frappe.ValidationError):  # nothing new recorded into it either
			self.pending_deposit()
		with self.assertRaises(frappe.MandatoryError):
			self.as_user(self.admin, mc.reopen_month, str(self.month), "", COMPANY)
		self.as_user(self.admin, mc.reopen_month, str(self.month), "a late supplier invoice", COMPANY)
		self.assertFalse(mc.is_closed(COMPANY, self.day))
		journal(self.post, self.bank, AMOUNT, self.day)
		self.assertEqual(frappe.get_doc(mc.CLOSE, name).reopens[0].reason, "a late supplier invoice")
		self.assertTrue(
			frappe.db.exists("SP Audit Log", {"action": "Month reopened", "reference_name": name})
		)


class TestRefused(MonthCase):
	def test_the_current_month_and_someone_else_cannot_close(self):
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.admin, mc.close_month, str(get_first_day(today())), COMPANY, {})
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.driver, mc.checklist, str(self.month), COMPANY)
