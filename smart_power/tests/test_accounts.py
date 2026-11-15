"""The chart of accounts: official, transit and custody accounts, and who sees them (SP-26)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_finance.accounts import (
	account_query_conditions,
	holder_account,
	mode_for_method,
	my_balances,
	seed_accounts,
)
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"


class TestAccounts(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_official_accounts_sit_under_bank_accounts(self):
		official = frappe.get_all(
			"Account",
			{"company": COMPANY, "sp_account_kind": "Official"},
			["account_name", "account_type", "parent_account"],
		)
		self.assertEqual(
			{a.account_name for a in official},
			{"Smart Power Bank Misr", "Mohamed Soliman InstaPay", "The Post", "Vodafone Cash"},
		)
		for a in official:
			self.assertEqual(a.account_type, "Bank")
			self.assertEqual(
				frappe.db.get_value("Account", a.parent_account, "account_name"), "Bank Accounts"
			)
		safe = frappe.db.get_value(
			"Account",
			{"company": COMPANY, "account_name": "Showroom Safe"},
			["sp_account_kind", "parent_account"],
			as_dict=True,
		)
		self.assertEqual(safe.sp_account_kind, "Transit")
		self.assertEqual(frappe.db.get_value("Account", safe.parent_account, "account_name"), "Cash In Hand")

	def test_seeding_twice_changes_nothing(self):
		before = frappe.db.count("Account", {"company": COMPANY})
		seed_accounts(COMPANY)
		self.assertEqual(frappe.db.count("Account", {"company": COMPANY}), before)

	def test_ticking_on_the_user_makes_their_transit_and_custody_accounts(self):
		from smart_power.sp_core.services.company import COMPANY_SETTINGS

		frappe.db.set_single_value(COMPANY_SETTINGS, "company", COMPANY)
		user = frappe.get_doc("User", make_user("sp.acc.mostafa@example.com", ("installation_manager",)))
		user.sp_create_transit_account = 1
		user.sp_create_custody_account = 1
		user.save()
		transit = frappe.db.get_value(
			"Account",
			{"sp_holder": user.name, "sp_account_kind": "Transit"},
			["account_type", "parent_account"],
			as_dict=True,
		)
		custody = frappe.db.get_value(
			"Account",
			{"sp_holder": user.name, "sp_account_kind": "Custody"},
			["parent_account"],
			as_dict=True,
		)
		self.assertEqual(transit.account_type, "Cash")
		self.assertEqual(
			frappe.db.get_value("Account", transit.parent_account, "account_name"), "Cash In Hand"
		)
		self.assertEqual(frappe.db.get_value("Account", custody.parent_account, "account_name"), "Custody")
		user.save()  # again: still one of each
		self.assertEqual(frappe.db.count("Account", {"sp_holder": user.name}), 2)

	def test_others_see_only_their_own_money(self):
		camelia = make_user("sp.acc.camelia@example.com", ("customer_followup",))
		mohamed = make_user("sp.acc.mohamed@example.com", ("customer_followup",))
		mine = holder_account(camelia, "Transit", COMPANY)
		theirs = holder_account(mohamed, "Transit", COMPANY)
		frappe.set_user(camelia)
		seen = set(frappe.get_list("Account", {"company": COMPANY}, pluck="name", limit_page_length=0))
		self.assertIn(mine, seen)
		self.assertNotIn(theirs, seen)
		self.assertNotIn(
			frappe.db.get_value("Account", {"company": COMPANY, "account_name": "Smart Power Bank Misr"}),
			seen,
		)
		self.assertEqual([b["name"] for b in my_balances()], [mine])
		frappe.set_user("Administrator")
		self.assertEqual(account_query_conditions("Administrator"), "")

	def test_a_missing_mode_of_payment_is_left_out(self):
		# found in CI: a site whose modes are not seeded yet still posts the payment
		from unittest.mock import patch

		with patch("frappe.db.exists", return_value=False):
			self.assertIsNone(mode_for_method("Payment Method-INSTAPAY"))

	def test_a_payment_method_has_its_mode_of_payment(self):
		self.assertEqual(mode_for_method("Payment Method-INSTAPAY"), "InstaPay")
		row = frappe.db.get_value(
			"Mode of Payment Account", {"parent": "InstaPay", "company": COMPANY}, "default_account"
		)
		self.assertEqual(frappe.db.get_value("Account", row, "account_name"), "Mohamed Soliman InstaPay")
