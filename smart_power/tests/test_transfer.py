"""Transfer / deposit between money accounts (SP-117)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_finance.accounts import holder_account, seed_accounts
from smart_power.sp_finance.confirmations import pending, preview
from smart_power.sp_finance.transfer import confirm, reject, sources
from smart_power.sp_finance.transit import days_held
from smart_power.tests.test_transit import journal
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule

load_erpnext_test_data()

COMPANY = "_Test Company"
PHOTO = "/files/deposit.jpg"


def balance(account):
	from erpnext.accounts.utils import get_balance_on

	return flt(get_balance_on(account, company=COMPANY, ignore_account_permission=True))


class TestTransfer(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)

	def setUp(self):
		set_rule("transfer_over_balance", "Warn", warn_needs_reason=0)
		self.driver = make_user("sp.tf.driver@example.com", ("custody_holder",))
		self.other = make_user("sp.tf.other@example.com", ("custody_holder",))
		self.admin = make_user("sp.tf.admin@example.com", ("admin",))
		self.cash = holder_account(self.driver, "Transit", COMPANY)
		self.other_cash = holder_account(self.other, "Transit", COMPANY)
		acc = lambda n: frappe.db.get_value("Account", {"company": COMPANY, "account_name": n})  # noqa: E731
		self.post, self.bank = acc("The Post"), acc("Smart Power Bank Misr")
		self.receivable = frappe.get_cached_value("Company", COMPANY, "default_receivable_account")
		# each test starts from an empty transit account (tests share a transaction)
		for voucher in set(
			frappe.get_all("GL Entry", {"account": self.cash, "is_cancelled": 0}, pluck="voucher_no")
		):
			je = frappe.get_doc("Journal Entry", voucher)
			if je.docstatus == 1:
				je.cancel()

	def tearDown(self):
		frappe.set_user("Administrator")

	def transfer(self, user, src, dst, amount, photo=PHOTO, submit=True):
		frappe.set_user(user)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SP Transfer",
					"from_account": src,
					"to_account": dst,
					"amount": amount,
					"work_date": today(),
					"receipt_photo": photo,
				}
			).insert()
			if submit:
				doc.submit()
			return doc
		finally:
			frappe.set_user("Administrator")

	def test_the_driver_deposits_3200_to_the_post(self):
		journal(self.cash, self.receivable, 3200, add_days(today(), -2))
		post_before, cash_before = balance(self.post), balance(self.cash)
		doc = self.transfer(self.driver, self.cash, self.post, 3200)
		self.assertEqual(doc.status, "Pending")
		self.assertEqual(balance(self.cash), cash_before)  # nothing moves before the admin confirms
		frappe.set_user(self.admin)
		self.assertIn(doc.name, [i["name"] for i in pending()["items"]])  # in A1
		lines = preview("SP Transfer", doc.name)
		self.assertEqual(
			{(line["account"], line["debit"], line["credit"]) for line in lines},
			{(self.post, 3200, 0), (self.cash, 0, 3200)},
		)
		confirm(doc.name)
		frappe.set_user("Administrator")
		self.assertEqual(balance(self.post) - post_before, 3200)
		self.assertEqual(balance(self.cash) - cash_before, -3200)
		self.assertEqual(days_held(self.cash), 0)  # settled: days held resets (SP-116)

	def test_someone_elses_transit_is_never_offered(self):
		self.assertEqual(sources(COMPANY, self.driver), [self.cash])
		self.assertNotIn(self.other_cash, sources(COMPANY, self.driver))
		with self.assertRaises(frappe.PermissionError):
			self.transfer(self.driver, self.other_cash, self.post, 100, submit=False)

	def test_the_admins_official_transfer_posts_at_once_and_is_audited(self):
		before = balance(self.bank)
		doc = self.transfer(self.admin, self.post, self.bank, 1000, photo=None)
		doc.reload()
		self.assertEqual(
			(doc.status, frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus")),
			("Confirmed", 1),
		)
		self.assertEqual(balance(self.bank) - before, 1000)
		self.assertTrue(frappe.db.exists("SP Audit Log", {"reference_name": doc.name}))

	def test_reject_posts_nothing_and_tasks_the_recorder(self):
		journal(self.cash, self.receivable, 500, today())
		doc = self.transfer(self.driver, self.cash, self.post, 500)
		frappe.set_user(self.admin)
		reject(doc.name, "الإيصال غير واضح")
		frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual((doc.status, doc.journal_entry), ("Rejected", None))
		self.assertTrue(
			frappe.db.exists(
				"SP Task", {"reference_name": doc.name, "assigned_to": self.driver, "status": "Open"}
			)
		)

	def test_checks(self):
		with self.assertRaises(frappe.ValidationError):
			self.transfer(self.admin, self.post, self.post, 100, submit=False)  # from = to
		with self.assertRaises(frappe.ValidationError):
			self.transfer(self.driver, self.cash, self.post, 100, photo=None, submit=False)  # no receipt
		# more than the transit holds: a warning, kept for review
		doc = self.transfer(self.driver, self.cash, self.post, 999999, submit=False)
		self.assertTrue(
			frappe.db.exists("SP Rule Hit", {"rule_key": "transfer_over_balance", "reference_name": doc.name})
		)
