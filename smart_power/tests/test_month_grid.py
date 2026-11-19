"""W2 month grid (SP-111): the vehicle's month adds up, ends on the operator's balance, and keeps
Smart Power's own jobs and the office's receipts apart."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, flt, today

from smart_power.sp_finance.accounts import CUSTODY, TRANSIT, holder_account, seed_accounts
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_finance.transfer import confirm
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import field_entry as fe
from smart_power.sp_winch import month_grid as mg
from smart_power.sp_winch import receipts as wr
from smart_power.sp_winch.report.sp_winch_month_grid.sp_winch_month_grid import execute
from smart_power.tests.test_bookings import employee
from smart_power.tests.test_field_entry import balance, list_value
from smart_power.tests.test_purchase_orders import station
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
AGREED, NOW, LATER, OLD = 2000, 500, 700, 100
FUEL, WAGE, SHOP, DEPOSIT, STATION_JOB = 300, 200, 150, 400, 3000
PHONE = "01001110111"


class TestMonthGrid(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		seed_centers(COMPANY)
		cls.operator = make_user("sp.mg.operator@example.com", ("winch_operator",))
		cls.manager = make_user("sp.mg.manager@example.com", ("winch_manager",))
		found = employee(cls.operator, "SP111 Operator")
		cls.worker = getattr(found, "name", found)
		cls.job_type = list_value("Job Type", "PUMP_DOWN")
		cls.fuel = list_value("Field Expense", "FUEL")
		cls.wage = list_value("Field Expense", "WORKER_WAGE")
		cls.cash = list_value("Payment Method", "CASH")
		cls.official = frappe.db.get_value("Account", {"company": COMPANY, "sp_account_kind": "Official"})
		plate = "SP111-JUMBO"
		if not frappe.db.exists("Vehicle", plate):
			frappe.get_doc(
				{"doctype": "Vehicle", "license_plate": plate, "sp_vehicle_type": "Jumbo", "company": COMPANY}
			).insert()
		cls.vehicle = plate
		cls.year, cls.month = int(today()[:4]), int(today()[5:7])

	def setUp(self):
		set_setting(account_map=[], field_entry_lock_days=3, winch_discount_role="SP Winch Manager")
		fe.seed_account_map(COMPANY)
		frappe.db.delete(wr.RECEIPT)
		frappe.db.delete(wr.ALLOCATION)
		frappe.db.delete(fe.ENTRY, {"vehicle": self.vehicle})
		self.addCleanup(frappe.set_user, "Administrator")

	def log(self, **values):
		frappe.set_user(self.operator)
		try:
			name = fe.save_entry({"vehicle": self.vehicle, "work_date": today(), **values})
		finally:
			frappe.set_user("Administrator")
		return frappe.get_doc(fe.ENTRY, name)

	def outside_job(self, **values):
		return self.log(
			**{
				"entry_kind": "Job",
				"job_type": self.job_type,
				"for_kind": "Outside",
				"customer_name": "SP111 Farmer",
				"customer_phone": PHONE,
				"place": "SP111 Farm",
				"agreed_amount": AGREED,
				"received_now": NOW,
				"received_method": self.cash,
				**values,
			}
		)

	def grid(self):
		return mg.month_rows(self.vehicle, self.year, self.month)

	def totals(self):
		return mg.month_totals(self.vehicle, self.year, self.month)

	def test_the_month_adds_up_and_ends_on_the_operators_balance(self):
		# earlier tests of this class leave postings behind, so the books are read as a delta
		transit = holder_account(self.operator, TRANSIT, COMPANY)
		custody = holder_account(self.operator, CUSTODY, COMPANY)
		books_before = balance(transit) + balance(custody)
		old = self.log(
			entry_kind="Expense", expense_type=self.fuel, amount=OLD, paid_from="Custody"
		)  # last month: the opening balance
		frappe.db.set_value(fe.ENTRY, old.name, "work_date", add_to_date(today(), months=-1))
		job = self.outside_job()
		self.log(
			entry_kind="Money",
			money_kind="Received",
			related_job=job.name,
			amount=LATER,
			received_method=self.cash,
		)
		self.log(entry_kind="Expense", expense_type=self.fuel, amount=FUEL, paid_from="Custody")
		self.log(
			entry_kind="Expense", expense_type=self.wage, amount=WAGE, paid_from="Custody", worker=self.worker
		)
		self.log(entry_kind="Expense", expense_type=self.fuel, amount=SHOP, paid_from="Shop cash")
		deposit = self.log(
			entry_kind="Money",
			money_kind="Deposit",
			amount=DEPOSIT,
			to_account=self.official,
			photo="/files/sp111.jpg",
		)
		rows = self.grid()
		self.assertEqual(rows[0]["item"], "Balance from the month before")
		self.assertEqual(rows[0]["balance"], -OLD)
		pending = self.totals()
		self.assertEqual(pending["deposited"], -DEPOSIT)
		self.assertEqual(pending["balance"], -OLD + NOW + LATER - FUEL - WAGE)  # not handed in yet
		confirm(deposit.transfer)
		totals = self.totals()
		self.assertEqual(totals["paid"], NOW + LATER)
		self.assertEqual((totals["wages"], totals["running"], totals["sp_expenses"]), (-WAGE, -FUEL, -SHOP))
		self.assertEqual(totals["balance"], -OLD + NOW + LATER - FUEL - WAGE - DEPOSIT)
		self.assertEqual(totals["balance"], balance(transit) + balance(custody) - books_before)
		self.assertEqual(totals["revenue"], NOW + LATER)
		self.assertEqual(totals["costs"], -(WAGE + FUEL + SHOP))
		self.assertEqual(totals["uncollected"], AGREED - NOW - LATER)

	def test_a_station_job_sits_apart_from_outside_revenue(self):
		self.log(
			entry_kind="Job",
			job_type=self.job_type,
			for_kind="Station",
			station=station().name,
			agreed_amount=STATION_JOB,
		)
		row = next(r for r in self.grid() if r.get("sp_jobs"))
		self.assertEqual(row["sp_jobs"], STATION_JOB)
		self.assertNotIn("agreed", row)
		totals = self.totals()
		self.assertEqual((totals["agreed"], totals["sp_jobs"]), (0, STATION_JOB))
		self.assertEqual(totals["revenue"], STATION_JOB)

	def test_an_office_receipt_shows_on_its_day_without_touching_the_balance(self):
		job = self.outside_job()
		doc = frappe.get_doc(
			{
				"doctype": wr.RECEIPT,
				"customer": job.customer,
				"amount": AGREED - NOW - 50,
				"method": self.cash,
				"allocations": [
					{
						"job": job.name,
						"amount": AGREED - NOW - 50,
						"discount": 50,
						"discount_reason": "Old customer",
					}
				],
			}
		)
		frappe.set_user(self.manager)
		try:
			doc.insert()
		finally:
			frappe.set_user("Administrator")
		rows = self.grid()
		office = next(r for r in rows if "Collected at the office" in r["item"])
		self.assertEqual((office["paid"], office["discount"]), (AGREED - NOW - 50, 50))
		totals = self.totals()
		self.assertEqual(totals["balance"], NOW)  # the office money never reached the operator
		self.assertEqual(totals["uncollected"], 0)
		self.assertEqual(totals["discount"], 50)
		self.assertEqual(totals["collection_rate"], (AGREED - 50) / AGREED)

	def test_the_report_renders_the_sheets_columns(self):
		self.outside_job()
		columns, rows, _msg, _chart, cards = execute(
			{"vehicle": self.vehicle, "year": self.year, "month": self.month}
		)
		order = [c["fieldname"] for c in columns]
		self.assertEqual(
			order[:9],
			["work_date", "item", "days", "agreed", "paid", "wages", "running", "deposited", "balance"],
		)
		self.assertEqual(rows[-1]["item"], "Total")
		self.assertEqual(rows[-1]["balance"], NOW)
		self.assertTrue(any(card["label"] == "Collection Rate" for card in cards))
		with self.assertRaises(frappe.ValidationError):
			execute({"month": self.month})

	def test_the_year_summary_lines_up_twelve_months_and_their_total(self):
		from smart_power.sp_winch.report.sp_winch_year_summary.sp_winch_year_summary import (
			execute as year_execute,
		)

		self.outside_job()
		columns, rows = year_execute({"vehicle": self.vehicle, "year": self.year})
		self.assertEqual(len(rows), 13)
		month = rows[self.month - 1]
		self.assertEqual((month["month_number"], month["agreed"], month["paid"]), (self.month, AGREED, NOW))
		total = rows[-1]
		self.assertEqual((total["month"], total["agreed"], total["balance"]), ("Total", AGREED, NOW))
		self.assertEqual([c["fieldname"] for c in columns][:3], ["month", "agreed", "paid"])
