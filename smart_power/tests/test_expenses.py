"""A10 Expenses and petty cash (SP-123): every expense on its center, paid from what paid it."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_core.setup.seed import seed_list_values
from smart_power.sp_finance import centers
from smart_power.sp_finance import expenses as ex
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.report.sp_expenses_by_center_and_type.sp_expenses_by_center_and_type import (
	execute,
)
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
PETTY, FUEL = "Expense Type-PETTY_CASH", "Expense Type-FUEL"


class TestExpenses(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_list_values()
		seed_accounts(COMPANY)
		cls.made = centers.seed_centers(COMPANY)
		cls.accountant = make_user("sp.ex.accountant@example.com", ("accountant",))
		cls.cashier = make_user("sp.ex.cashier@example.com", ("showroom_cashier",))
		cls.official = frappe.db.get_value(
			"Account", {"company": COMPANY, "sp_account_kind": "Official", "is_group": 0}, order_by="name asc"
		)

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_setting(account_map=[], **{f"center_{key}": name for key, name in self.made.items()})
		ex.seed_account_map(COMPANY)

	def expense(self, user=None, submit=True, **values):
		frappe.set_user(user or self.accountant)
		try:
			doc = frappe.get_doc(
				{
					"doctype": ex.EXPENSE,
					"company": COMPANY,
					"work_date": today(),
					"amount": 300,
					"expense_type": PETTY,
					"center_type": "Project",
					"paid_from_kind": "Official account",
					"paid_from_account": self.official,
					**values,
				}
			).insert()
			if submit:
				doc.submit()
			return doc
		finally:
			frappe.set_user("Administrator")

	def lines(self, doc):
		return frappe.get_all(
			"Journal Entry Account",
			{"parent": doc.journal_entry},
			["account", "debit_in_account_currency", "credit_in_account_currency", "cost_center", "project"],
		)

	def test_project_petty_cash_with_no_station_goes_to_the_indirect_pool(self):
		doc = self.expense()
		self.assertEqual(doc.cost_center, self.made["indirect"])
		debit = next(r for r in self.lines(doc) if flt(r.debit_in_account_currency))
		self.assertEqual(
			(debit.cost_center, flt(debit.debit_in_account_currency)), (self.made["indirect"], 300)
		)
		self.assertEqual(frappe.db.get_value("Account", debit.account, "account_name"), "Petty Cash Expenses")

	def test_paid_by_the_owner_credits_the_owner_current_account(self):
		doc = self.expense(
			center_type="Showroom", expense_type=FUEL, paid_from_kind="Company Owner", paid_from_account=None
		)
		credit = next(r for r in self.lines(doc) if flt(r.credit_in_account_currency))
		self.assertEqual(frappe.db.get_value("Account", credit.account, "account_name"), ex.OWNER_ACCOUNT)
		self.assertEqual(frappe.db.get_value("Account", credit.account, "root_type"), "Liability")
		self.assertEqual(doc.cost_center, self.made["showroom"])

	def test_a_station_expense_carries_its_project_and_is_listed_for_review(self):
		quote = make_quotation(rate=1000, valid_days=3)
		quote.submit()
		frappe.db.set_value("SP Case", quote.sp_case, "accepted_quotation", quote.name)
		station = frappe.get_doc(
			{"doctype": "SP Station", "case": quote.sp_case, "company": COMPANY}
		).insert()
		doc = self.expense(station=station.name, expense_type=FUEL)
		self.assertEqual((doc.project, doc.cost_center), (station.project, self.made["projects"]))
		debit = next(r for r in self.lines(doc) if flt(r.debit_in_account_currency))
		self.assertEqual(debit.project, station.project)
		self.assertTrue(
			frappe.db.exists("SP Review Item", {"category": "Expense", "reference_name": doc.name})
		)

	def test_the_cashier_pays_from_the_shop_cash_only(self):
		with self.assertRaises(frappe.PermissionError):
			self.expense(user=self.cashier, center_type="Showroom")
		doc = self.expense(
			user=self.cashier, center_type="Showroom", paid_from_kind="Shop cash", paid_from_account=None
		)
		credit = next(r for r in self.lines(doc) if flt(r.credit_in_account_currency))
		self.assertEqual(
			credit.account,
			frappe.db.get_value("Account", {"company": COMPANY, "account_name": "Showroom Safe"}),
		)

	def test_an_official_account_is_required_to_be_official(self):
		transit = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_name": "Showroom Safe", "is_group": 0}
		)
		with self.assertRaises(frappe.ValidationError):
			self.expense(paid_from_account=transit)

	def test_the_list_totals_by_center_and_type(self):
		# centers no other test of the class uses (they share one transaction)
		self.expense(amount=100, center_type="Jumbo")
		self.expense(amount=250, center_type="Jumbo")
		self.expense(amount=70, center_type="Winch", expense_type=FUEL)
		frappe.set_user(self.accountant)
		_columns, rows = execute({"from_date": today(), "to_date": today()})
		frappe.set_user("Administrator")
		by = {(r["cost_center"], r["count"]): flt(r["amount"]) for r in rows}
		self.assertEqual(by.get((self.made["jumbo"], 2)), 350)
		self.assertEqual(by.get((self.made["winch"], 1)), 70)
