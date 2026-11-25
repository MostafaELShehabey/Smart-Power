"""Worker advances and crew salaries (SP-181): an advance is paid back by salary deduction or in
cash, and each worker's balance follows."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, flt, get_first_day, today

from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_finance.posting import postings
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import crew_pay as cp
from smart_power.tests.test_field_entry import balance
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
ADVANCE, INSTALLMENT, SALARY, MONTHS = 6000, 1000, 5000, 6


class TestCrewPay(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		seed_centers(COMPANY)
		cls.manager = make_user("sp.cp.manager@example.com", ("winch_manager",))
		cls.reviewer = make_user("sp.cp.reviewer@example.com", ("winch_reviewer",))
		frappe.defaults.set_user_default("Company", COMPANY, cls.manager)
		cls.official = frappe.db.get_value(
			"Account", {"company": COMPANY, "sp_account_kind": "Official", "is_group": 0}
		)
		plate = "SP181-WINCH"
		if not frappe.db.exists("Vehicle", plate):
			frappe.get_doc(
				{"doctype": "Vehicle", "license_plate": plate, "sp_vehicle_type": "Winch", "company": COMPANY}
			).insert()
		cls.vehicle = plate
		cls.driver = cls.employee("SP181 Driver", salary=SALARY)
		cls.worker = cls.employee("SP181 Daily", daily=True)

	@classmethod
	def employee(cls, name, salary=0, daily=False):
		found = frappe.db.get_value("Employee", {"first_name": name})
		if found:
			return found
		return (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": name,
					"gender": "Male",
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
					"company": COMPANY,
					"status": "Active",
					"sp_monthly_salary": salary,
					"sp_is_daily_worker": 1 if daily else 0,
					"sp_daily_wage": 250 if daily else 0,
				}
			)
			.insert()
			.name
		)

	def setUp(self):
		set_setting(account_map=[], worker_advance_repayment="Salary deduction")
		cp.seed_account_map(COMPANY)
		frappe.db.delete(cp.SALARY)
		frappe.db.delete(cp.REPAYMENT)
		frappe.db.delete(cp.ADVANCE)
		self.addCleanup(frappe.set_user, "Administrator")

	def as_manager(self, action, *args, **kwargs):
		frappe.set_user(self.manager)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def advance(self, employee=None, amount=ADVANCE, installment=INSTALLMENT):
		doc = frappe.get_doc(
			{
				"doctype": cp.ADVANCE,
				"employee": employee or self.driver,
				"vehicle": self.vehicle,
				"amount": amount,
				"installment_amount": installment,
				"paid_from": self.official,
			}
		)

		def make():
			doc.insert()
			doc.submit()
			return doc

		return self.as_manager(make)

	def salary(self, months_ago=0, employee=None):
		doc = frappe.get_doc(
			{
				"doctype": cp.SALARY,
				"employee": employee or self.driver,
				"vehicle": self.vehicle,
				"month": get_first_day(add_months(today(), -months_ago)),
				"paid_from": self.official,
			}
		)

		def make():
			doc.insert()
			doc.submit()
			return doc

		return self.as_manager(make)

	def test_an_advance_of_6000_is_deducted_1000_a_month_until_repaid(self):
		advances = cp._account(COMPANY, cp.ADVANCES_ACCOUNT)
		before = balance(advances)
		doc = self.advance()
		self.assertEqual(balance(advances) - before, ADVANCE)
		self.assertEqual(cp.worker_balance(self.driver), ADVANCE)
		for month in range(MONTHS, 0, -1):
			pay = self.salary(months_ago=month)
			self.assertEqual(
				(flt(pay.advance_deduction), flt(pay.net_amount)), (INSTALLMENT, SALARY - INSTALLMENT)
			)
		doc.reload()
		self.assertEqual(
			(doc.status, flt(doc.outstanding_amount), len(doc.repayments)), ("Repaid", 0, MONTHS)
		)
		self.assertEqual(balance(advances) - before, 0)
		self.assertEqual(cp.worker_balance(self.driver), 0)
		after = self.salary()  # the seventh month: nothing left to deduct
		self.assertEqual((flt(after.advance_deduction), flt(after.net_amount)), (0, SALARY))
		salaries = cp._account(COMPANY, cp.SALARIES_ACCOUNT)
		self.assertEqual(balance(salaries, voucher_no=("in", postings(after))), SALARY)

	def test_the_advance_and_salary_name_the_worker_from_the_server(self):
		# BUG-10: the form no longer fetches them from Employee (the winch manager may not read it)
		advance = self.advance(self.worker, amount=500, installment=500)
		self.assertEqual((advance.employee_name, advance.daily_worker), ("SP181 Daily", 1))
		self.assertEqual(self.salary().employee_name, "SP181 Driver")

	def test_cancelling_a_salary_gives_the_installment_back(self):
		doc = self.advance()
		pay = self.salary()
		self.as_manager(pay.cancel)
		doc.reload()
		self.assertEqual((flt(doc.outstanding_amount), len(doc.repayments), doc.status), (ADVANCE, 0, "Open"))

	def test_in_cash_mode_salaries_are_paid_in_full_and_the_cash_repays(self):
		set_setting(worker_advance_repayment="Cash")
		doc = self.advance()
		self.assertEqual(flt(self.salary().advance_deduction), 0)
		self.as_manager(cp.repay_in_cash, doc.name, ADVANCE - INSTALLMENT, self.official)
		doc.reload()
		self.assertEqual((flt(doc.outstanding_amount), doc.repayments[0].kind), (INSTALLMENT, "Cash"))
		with self.assertRaises(frappe.ValidationError):
			self.as_manager(cp.repay_in_cash, doc.name, INSTALLMENT + 1, self.official)

	def test_a_daily_worker_repays_in_cash_only(self):
		doc = self.advance(employee=self.worker, amount=500, installment=100)
		self.assertEqual(cp._plan(frappe._dict(employee=self.worker, gross_amount=SALARY)), [])
		self.as_manager(cp.repay_in_cash, doc.name, 500, self.official)
		doc.reload()
		self.assertEqual(doc.status, "Repaid")

	def test_one_salary_a_month_and_only_the_winch_office_pays(self):
		self.salary()
		with self.assertRaises(frappe.ValidationError):
			self.salary()
		doc = self.advance()
		frappe.set_user(self.reviewer)
		try:
			with self.assertRaises(frappe.PermissionError):
				cp.repay_in_cash(doc.name, INSTALLMENT, self.official)
		finally:
			frappe.set_user("Administrator")

	def test_the_salary_form_starts_from_the_salary_and_the_debt(self):
		self.advance()
		start = self.as_manager(cp.salary_start, self.driver)
		self.assertEqual(
			(start["monthly_salary"], start["owed"], start["daily_worker"]), (SALARY, ADVANCE, False)
		)
		frappe.set_user(self.reviewer)
		try:
			with self.assertRaises(frappe.PermissionError):
				cp.salary_start(self.driver)
		finally:
			frappe.set_user("Administrator")

	def test_worker_balances_and_the_month_grid_show_the_crew(self):
		from smart_power.sp_winch.month_grid import month_totals
		from smart_power.sp_winch.report.sp_worker_balances.sp_worker_balances import execute

		self.advance()
		pay = self.salary()
		_columns, rows = execute({"vehicle": self.vehicle})
		row = next(r for r in rows if r["employee"] == self.driver)
		self.assertEqual(
			(row["amount"], row["repaid"], row["outstanding"], row["last_kind"]),
			(ADVANCE, INSTALLMENT, ADVANCE - INSTALLMENT, "Salary deduction"),
		)
		year, month = int(today()[:4]), int(today()[5:7])
		totals = month_totals(self.vehicle, year, month)
		self.assertEqual(totals["wages"], -SALARY)  # the whole salary is the month's cost
		self.assertEqual(totals["balance"], 0)  # paid from an official account: no one's cash moved
		self.assertEqual(pay.docstatus, 1)
