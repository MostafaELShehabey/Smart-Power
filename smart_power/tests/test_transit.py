"""Cash held by a person: days held and the cash-held-too-long alert (SP-116)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.sp_finance.accounts import holder_account, seed_accounts
from smart_power.sp_finance.transit import check_cash_held, days_held, oldest_open_date
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"


def journal(debit, credit, amount, on, party=None):
	accounts = [
		{"account": debit, "debit_in_account_currency": amount},
		{"account": credit, "credit_in_account_currency": amount},
	]
	for row in accounts:
		if frappe.db.get_value("Account", row["account"], "account_type") == "Receivable":
			row.update(party_type="Customer", party=party or "_Test Customer")
	je = frappe.get_doc(
		{"doctype": "Journal Entry", "company": COMPANY, "posting_date": on, "accounts": accounts}
	).insert()
	je.submit()
	return je


class TestTransit(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)

	def setUp(self):
		set_setting(cash_held_limit_days=3)
		self.mohamed = make_user("sp.tr.mohamed@example.com", ("customer_followup",))
		self.admin = make_user("sp.tr.admin@example.com", ("admin",))
		self.cash = holder_account(self.mohamed, "Transit", COMPANY)
		self.bank = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_name": "Smart Power Bank Misr"}
		)
		self.receivable = frappe.get_cached_value("Company", COMPANY, "default_receivable_account")
		# start every test from an empty account
		for name in frappe.get_all("GL Entry", {"account": self.cash, "is_cancelled": 0}, pluck="voucher_no"):
			je = frappe.get_doc("Journal Entry", name)
			if je.docstatus == 1:
				je.cancel()

	def alerts(self):
		return frappe.get_all(
			"Notification Log", {"document_type": "Account", "document_name": self.cash}, pluck="for_user"
		)

	def test_received_on_day_1_with_a_3_day_limit_alerts_on_day_4(self):
		journal(self.cash, self.receivable, 5000, add_days(today(), -3))  # day 1; today is day 4
		self.assertEqual(days_held(self.cash), 4)
		self.assertIn(self.cash, check_cash_held())
		self.assertTrue({self.mohamed, self.admin} <= set(self.alerts()))
		self.assertTrue(
			frappe.db.exists("SP Rule Hit", {"rule_key": "cash_held_too_long", "reference_name": self.cash})
		)

	def test_within_the_limit_no_alert(self):
		journal(self.cash, self.receivable, 5000, add_days(today(), -1))
		self.assertEqual(days_held(self.cash), 2)
		self.assertNotIn(self.cash, check_cash_held())

	def test_deposited_resets_days_held_and_stops_the_alert(self):
		journal(self.cash, self.receivable, 5000, add_days(today(), -3))
		journal(self.bank, self.cash, 5000, today())  # deposited (SP-117 makes this a transfer)
		self.assertIsNone(oldest_open_date(self.cash))
		self.assertEqual(days_held(self.cash), 0)
		self.assertNotIn(self.cash, check_cash_held())

	def test_first_in_first_out(self):
		journal(self.cash, self.receivable, 3000, add_days(today(), -5))
		journal(self.cash, self.receivable, 2000, add_days(today(), -1))
		journal(self.bank, self.cash, 3000, today())  # the oldest 3,000 is deposited
		self.assertEqual(oldest_open_date(self.cash), frappe.utils.getdate(add_days(today(), -1)))

	def test_the_accounts_own_limit_wins(self):
		frappe.db.set_value("Account", self.cash, "sp_max_days_held", 10)
		journal(self.cash, self.receivable, 5000, add_days(today(), -5))
		self.assertNotIn(self.cash, check_cash_held())
		frappe.db.set_value("Account", self.cash, "sp_max_days_held", 0)

	def test_the_treasury_shows_days_held_and_is_the_admins(self):
		from smart_power.sp_finance.treasury import treasury

		journal(self.cash, self.receivable, 5000, add_days(today(), -3))
		data = treasury(COMPANY)
		row = next(r for r in data["transit"] if r["account"] == self.cash)
		self.assertEqual((row["days_held"], row["over"], row["balance"]), (4, True, 5000))
		official = {r["account_name"]: r for r in data["official"]}
		self.assertEqual(len(official), 4)
		self.assertTrue(official["Smart Power Bank Misr"]["bank_account"])  # for reconciliation
		frappe.set_user(make_user("sp.tr.camelia@example.com", ("customer_followup", "followup_all")))
		try:
			with self.assertRaises(frappe.PermissionError):
				treasury(COMPANY)
		finally:
			frappe.set_user("Administrator")
		roles = {r.role for r in frappe.get_doc("Page", "sp-treasury").roles}
		self.assertEqual(roles, {"SP Admin", "System Manager"})

	def test_the_holder_sees_their_days_held(self):
		from smart_power.sp_finance.accounts import my_balances

		journal(self.cash, self.receivable, 5000, add_days(today(), -3))
		frappe.set_user(self.mohamed)
		try:
			mine = my_balances()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual((mine[0]["days_held"], mine[0]["over"]), (4, True))
