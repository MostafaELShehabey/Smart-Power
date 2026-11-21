"""SH3 showroom deposit (SP-105): the cashier deposits the showroom box; the admin confirms it."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_core.services.company import COMPANY_SETTINGS
from smart_power.sp_finance import cash_box as cb
from smart_power.sp_finance import transfer as tf
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.confirmations import pending
from smart_power.sp_finance.transit import days_held
from smart_power.tests.test_transit import journal
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule

load_erpnext_test_data()

COMPANY, PHOTO = "_Test Company", "/files/sp105-deposit.png"
IN_HAND = 15000  # sp-allow-number: the story's cash in hand


def balance(account):
	from erpnext.accounts.utils import get_balance_on

	return flt(get_balance_on(account, company=COMPANY, ignore_account_permission=True))


class DepositCase(IntegrationTestCase):
	"""Each scenario is its own class, so its box starts from the same cash in hand."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)
		cls.cashier = make_user("sp.dep.cashier@example.com", ("showroom_cashier",))
		cls.admin = make_user("sp.dep.admin@example.com", ("admin",))
		cls.driver = make_user("sp.dep.driver@example.com", ("custody_holder",))
		acc = lambda n: frappe.db.get_value("Account", {"company": COMPANY, "account_name": n})  # noqa: E731
		cls.box, cls.post, cls.wallet = acc("Showroom Safe"), acc("The Post"), acc("Vodafone Cash")
		cls.other_transit = frappe.db.get_value(
			"Account",
			{"company": COMPANY, "sp_account_kind": "Transit", "name": ("!=", cls.box), "is_group": 0},
		)
		frappe.db.set_single_value(COMPANY_SETTINGS, "company", COMPANY)

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_rule("transfer_over_balance", "Warn", warn_needs_reason=0)
		# the box holds 15,000 of cash in hand
		top_up = IN_HAND - tf.in_hand(self.box)
		if top_up:
			sales = frappe.get_cached_value("Company", COMPANY, "default_income_account")
			if top_up > 0:
				journal(self.box, sales, top_up, today())
			else:
				journal(sales, self.box, -top_up, today())

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def deposit(self, to_account=None, amount=IN_HAND, photo=PHOTO, user=None):
		values = {
			"from_account": self.box,
			"to_account": to_account or self.post,
			"amount": amount,
			"work_date": today(),
			"reference_no": "SP105",
			"receipt_photo": photo,
		}
		return self.as_user(user or self.cashier, tf.record_transfer, values)


class TestCashierDeposits(DepositCase):
	def test_the_cashier_deposits_15000_to_the_post_and_a1_shows_it_with_the_photo(self):
		opts = self.as_user(self.cashier, tf.transfer_options, COMPANY)
		box = next(s for s in opts["sources"] if s["value"] == self.box)
		self.assertEqual((box["balance"], box["official_only"]), (IN_HAND, True))  # amount = cash in hand

		name = self.deposit()
		self.assertEqual(frappe.db.get_value(tf.TRANSFER, name, "status"), tf.PENDING)
		item = next(i for i in self.as_user(self.admin, pending)["items"] if i["name"] == name)
		self.assertEqual((item["amount"], item["photo"], item["account"]), (IN_HAND, PHOTO, self.post))

		# deposit pending: out of the box's cash in hand, not yet in the books
		self.assertEqual(tf.in_hand(self.box), 0)
		self.assertEqual(tf.pending_out(self.box), IN_HAND)
		self.assertEqual(balance(self.box), IN_HAND)
		day = frappe.get_doc(
			{"doctype": cb.DAY, "cash_account": self.box, "company": COMPANY, "day": today()}
		)
		state = cb.state(day)
		self.assertEqual([r.name for r in state["pending_deposits"]], [name])
		self.assertEqual((state["held"]["balance"], state["held"]["pending_deposits"]), (0, IN_HAND))


class TestAdminConfirms(DepositCase):
	def test_confirming_moves_15000_from_the_box_to_the_post_and_resets_the_days(self):
		name = self.deposit()
		post_before, box_before = balance(self.post), balance(self.box)
		self.assertGreater(days_held(self.box), 0)
		entry = self.as_user(self.admin, tf.confirm, name)
		self.assertEqual(balance(self.post) - post_before, IN_HAND)
		self.assertEqual(balance(self.box) - box_before, -IN_HAND)
		self.assertEqual(days_held(self.box), 0)
		self.assertEqual(frappe.db.get_value("Journal Entry", entry, "cheque_no"), "SP105")
		self.assertEqual(tf.pending_out(self.box), 0)


class TestAnyOfficialAccount(DepositCase):
	def test_the_cashier_may_deposit_into_a_wallet(self):
		name = self.deposit(to_account=self.wallet)
		self.assertEqual(frappe.db.get_value(tf.TRANSFER, name, "to_account"), self.wallet)


class TestRefused(DepositCase):
	def test_no_photo_a_transit_target_and_someone_else_are_refused(self):
		with self.assertRaises(frappe.MandatoryError):
			self.deposit(photo=None)
		if self.other_transit:
			with self.assertRaises(frappe.ValidationError):
				self.deposit(to_account=self.other_transit)
		with self.assertRaises(frappe.PermissionError):
			self.deposit(user=self.driver)
		self.assertNotIn(self.box, tf.sources(COMPANY, self.driver))


class TestOverTheCashInHand(DepositCase):
	def test_a_second_deposit_of_the_same_cash_warns(self):
		from smart_power.rules.finance import transfer_over_balance

		self.deposit()
		doc = frappe.get_doc(
			{
				"doctype": tf.TRANSFER,
				"company": COMPANY,
				"from_account": self.box,
				"to_account": self.post,
				"amount": IN_HAND,
				"work_date": today(),
			}
		)
		self.assertIsNotNone(transfer_over_balance(doc, None))  # 0 is left in hand
