"""G6 Profile (SP-42): my roles, language, notification channels, my custody and cash held."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.sp_core import profile
from smart_power.sp_finance import centers, custody
from smart_power.sp_finance.accounts import holder_account, seed_accounts
from smart_power.tests.test_transit import journal
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"


class TestProfile(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)

	def setUp(self):
		made = centers.seed_centers(COMPANY)
		set_setting(cash_held_limit_days=3, **{f"center_{k}": v for k, v in made.items()})
		set_rule("cash_held_too_long", "Warn", warn_needs_reason=0)
		self.indirect = made[centers.INDIRECT]
		self.admin = make_user("sp.pf.admin@example.com", ("admin",))
		self.mostafa = make_user("sp.pf.mostafa@example.com", ("custody_holder",))
		self.other = make_user("sp.pf.other@example.com", ("custody_holder",))
		self.bank = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_name": "Smart Power Bank Misr"}
		)

	def tearDown(self):
		frappe.set_user("Administrator")

	def mine(self, user):
		frappe.set_user(user)
		try:
			return profile.profile()
		finally:
			frappe.set_user("Administrator")

	def test_custody_5000_given_12_days_ago_3200_spent_shows_1800_and_12_days(self):
		frappe.set_user(self.admin)
		doc = frappe.get_doc(
			{
				"doctype": "SP Custody",
				"holder": self.mostafa,
				"company": COMPANY,
				"amount": 5000,
				"from_account": self.bank,
				"given_on": add_days(today(), -12),
			}
		).insert()
		doc.submit()
		frappe.set_user(self.mostafa)
		custody.add_expense(
			doc.name,
			{
				"amount": 3200,
				"expense_type": "Expense Type-OTHER",
				"center_type": "Center",
				"cost_center": self.indirect,
			},
		)
		name = custody.submit_settlement(doc.name)
		frappe.set_user(self.admin)
		custody.confirm(name)
		row = next(m for m in self.mine(self.mostafa)["money"] if m["kind"] == "Custody")
		self.assertEqual((row["balance"], row["days_held"], row["over"]), (1800, 12, False))

	def test_cash_held_past_the_limit_is_red_and_only_my_accounts_show(self):
		cash = holder_account(self.mostafa, "Transit", COMPANY)
		receivable = frappe.get_cached_value("Company", COMPANY, "default_receivable_account")
		journal(cash, receivable, 700, add_days(today(), -4))
		row = next(m for m in self.mine(self.mostafa)["money"] if m["account"] == cash)
		self.assertEqual((row["balance"], row["days_held"], row["over"]), (700, 5, True))
		self.assertNotIn(cash, [m["account"] for m in self.mine(self.other)["money"]])

	def test_roles_are_shown_read_only_in_my_language(self):
		frappe.db.set_value("User", self.mostafa, "language", "ar")
		data = self.mine(self.mostafa)
		self.assertIn("صاحب عهدة", [r["label"] for r in data["roles"]])
		frappe.db.set_value("User", self.mostafa, "language", "en")
		self.assertIn("Custody Holder", [r["label"] for r in self.mine(self.mostafa)["roles"]])
		self.assertEqual(data["user"], self.mostafa)

	def test_language_and_channels(self):
		frappe.set_user(self.mostafa)
		self.assertEqual(profile.set_language("en"), "en")
		self.assertEqual(frappe.db.get_value("User", self.mostafa, "language"), "en")
		with self.assertRaises(frappe.ValidationError):
			profile.set_language("fr")
		self.assertEqual(profile.set_channels({"email": False}), {"in_app": True, "email": False})
		self.assertFalse(
			frappe.db.get_value("Notification Settings", self.mostafa, "enable_email_notifications")
		)
		frappe.set_user("Administrator")
		self.assertTrue(
			frappe.db.get_value("Notification Settings", self.other, "enable_email_notifications")
			in (None, 1)
		)
