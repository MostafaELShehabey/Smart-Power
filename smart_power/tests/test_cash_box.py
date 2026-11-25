"""SH2 Showroom cash box (SP-104): the day's expected closing, the counted close, the limits."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_finance import cash_box as cb
from smart_power.sp_finance import centers
from smart_power.sp_finance import expenses as ex
from smart_power.sp_finance import showroom_payment as sp
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import ensure_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_field_entry import list_value
from smart_power.tests.utils import (
	load_erpnext_test_data,
	make_quotation,
	make_user,
	set_rule,
	set_setting,
	sign_contract,
)

load_erpnext_test_data()

COMPANY, DAY = "_Test Company", "SP Cash Box Day"
OPENING, SALES, STATION_PAYMENT, EXPENSE, DEPOSIT = 2000, 5500, 10000, 300, 15000
EXPECTED = 2200  # 2,000 + 5,500 + 10,000 - 300 - 15,000


class CashBoxCase(IntegrationTestCase):
	"""The box's helpers; each scenario is its own class, so its day starts empty."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		cls.made = centers.seed_centers(COMPANY)
		cls.cashier = make_user("sp.cb.cashier@example.com", ("showroom_cashier",))
		cls.admin = make_user("sp.cb.admin@example.com", ("admin",))
		cls.cash = list_value("Payment Method", "CASH")
		cls.box = frappe.db.get_value("Account", {"company": COMPANY, "account_name": "Showroom Safe"})
		cls.post = frappe.db.get_value(
			"Account", {"company": COMPANY, "sp_account_kind": "Official", "is_group": 0}, order_by="name asc"
		)

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_setting(
			account_map=[], showroom_box_cash_limit=100000, **{f"center_{k}": v for k, v in self.made.items()}
		)
		ex.seed_account_map(COMPANY)
		cb.seed_account_map(COMPANY)
		set_rule("showroom_cash_over_limit", "Warn")
		frappe.defaults.set_user_default("Company", COMPANY, self.cashier)
		frappe.db.delete(DAY, {"cash_account": self.box})  # one open day per box

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def station(self):
		q = make_quotation(rate=50000, valid_days=3)
		q.submit()
		approve_version(q.name)
		result = ensure_contract(q.sp_case)
		sign_contract(result["sales_order"])
		return result["station"]

	def yesterday_closed_at(self, counted):
		frappe.get_doc(
			{
				"doctype": DAY,
				"cash_account": self.box,
				"company": COMPANY,
				"day": add_days(today(), -1),
				"status": cb.CONFIRMED,
				"counted": counted,
			}
		).db_insert()

	def the_day(self):
		"""Yesterday closed at 2,000; today: 5,500 of sales, a 10,000 station payment, a 300
		expense and a 15,000 deposit to the Post."""
		self.yesterday_closed_at(OPENING)
		self.as_user(
			self.cashier,
			sp.record,
			{"station": self.station(), "amount": STATION_PAYMENT, "method": self.cash},
		)
		expense = frappe.get_doc(
			{
				"doctype": ex.EXPENSE,
				"company": COMPANY,
				"work_date": today(),
				"amount": EXPENSE,
				"expense_type": "Expense Type-PETTY_CASH",
				"center_type": "Showroom",
				"paid_from_kind": "Shop cash",
			}
		)
		self.as_user(self.cashier, lambda: (expense.insert(), expense.submit()))
		deposit = frappe.get_doc(
			{
				"doctype": "SP Transfer",
				"company": COMPANY,
				"from_account": self.box,
				"to_account": self.post,
				"amount": DEPOSIT,
				"work_date": today(),
				"reference_no": "SP104",
				"receipt_photo": "/files/sp104-deposit.png",
			}
		)
		deposit.flags.ignore_permissions = True
		deposit.insert()
		deposit.submit()
		with patch.object(cb, "sales_in", return_value=SALES):  # the showroom sales come with SP-102
			name = self.as_user(self.cashier, cb.open_today, COMPANY)
			doc = frappe.get_doc(DAY, name)
			doc.save()
		return doc


class TestExpectedClosing(CashBoxCase):
	def test_the_expected_closing_is_2200(self):
		doc = self.the_day()
		self.assertEqual(
			(
				flt(doc.opening),
				flt(doc.sales_in),
				flt(doc.station_payments_in),
				flt(doc.expenses_out),
				flt(doc.deposits_out),
			),
			(OPENING, SALES, STATION_PAYMENT, EXPENSE, DEPOSIT),
		)
		self.assertEqual(flt(doc.expected_closing), EXPECTED)


class TestOpenDayIsCurrent(CashBoxCase):
	def test_an_expense_after_the_last_save_shows_on_the_form(self):
		"""BUG-15: the close dialog read the expected closing of the day's last save."""
		from frappe.desk.form.load import run_onload

		doc = self.the_day()
		later = frappe.get_doc(
			{
				"doctype": ex.EXPENSE,
				"company": COMPANY,
				"work_date": today(),
				"amount": 150,
				"expense_type": "Expense Type-PETTY_CASH",
				"center_type": "Showroom",
				"paid_from_kind": "Shop cash",
			}
		)
		self.as_user(self.cashier, lambda: (later.insert(), later.submit()))
		shown = frappe.get_doc(DAY, doc.name)
		with patch.object(cb, "sales_in", return_value=SALES):
			run_onload(shown)
		self.assertEqual(
			(flt(shown.expenses_out), flt(shown.expected_closing)), (EXPENSE + 150, EXPECTED - 150)
		)


class TestDayClose(CashBoxCase):
	def test_counted_2150_needs_a_reason_and_the_admin_confirm_posts_minus_50(self):
		doc = self.the_day()
		with patch.object(cb, "sales_in", return_value=SALES):
			with self.assertRaises(frappe.MandatoryError):
				self.as_user(self.cashier, cb.close_day, doc.name, 2150)
			self.as_user(self.cashier, cb.close_day, doc.name, 2150, "ورقة 50 ناقصة")
		doc.reload()
		self.assertEqual((doc.status, flt(doc.difference)), (cb.PENDING, -50))
		self.assertTrue(any(i["name"] == doc.name for i in cb.pending_items({})))
		entry = self.as_user(self.admin, cb.confirm, doc.name)
		lines = frappe.get_all(
			"Journal Entry Account",
			{"parent": entry},
			["account", "debit_in_account_currency", "credit_in_account_currency"],
		)
		short = next(r for r in lines if flt(r.debit_in_account_currency))
		self.assertEqual(frappe.db.get_value("Account", short.account, "account_name"), cb.OVER_SHORT_ACCOUNT)
		self.assertEqual(flt(short.debit_in_account_currency), 50)
		self.assertEqual(next(r for r in lines if flt(r.credit_in_account_currency)).account, self.box)
		self.assertEqual(frappe.db.get_value(DAY, doc.name, "status"), cb.CONFIRMED)


class TestNextDay(CashBoxCase):
	def test_the_next_day_opens_at_the_last_count(self):
		doc = self.the_day()
		with patch.object(cb, "sales_in", return_value=SALES):
			self.as_user(self.cashier, cb.close_day, doc.name, EXPECTED)
		nxt = frappe.get_doc(
			{"doctype": DAY, "cash_account": self.box, "company": COMPANY, "day": add_days(today(), 1)}
		).insert()
		self.assertEqual(flt(nxt.opening), EXPECTED)


class TestCashHeld(CashBoxCase):
	def test_cash_held_too_long_shows_the_days_and_at_block_stops_the_close(self):
		doc = self.the_day()
		with patch("smart_power.sp_finance.transit.days_held", return_value=9):
			state = cb.held(doc)
			self.assertTrue(state["over_days"])
			self.assertEqual(state["days"], 9)  # the page's red banner
			set_rule("showroom_cash_over_limit", "Block")
			# a Block queues its SP Rule Hit for after the rollback, and that write commits:
			# the class rollback would leave a hit on a day that no longer exists
			with (
				patch.object(cb, "sales_in", return_value=SALES),
				patch("smart_power.rules._log_blocks_after_rollback") as log_block,
			):
				with self.assertRaises(frappe.ValidationError):
					self.as_user(self.cashier, cb.close_day, doc.name, EXPECTED)
			self.assertEqual(log_block.call_args.args[1][0].spec.key, "showroom_cash_over_limit")
		self.assertEqual(frappe.db.get_value(DAY, doc.name, "status"), cb.OPEN)


class TestOneOpenDay(CashBoxCase):
	def test_one_open_day_per_box_and_only_the_cashier_or_admin(self):
		self.as_user(self.cashier, cb.open_today, COMPANY)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": DAY, "cash_account": self.box, "company": COMPANY, "day": add_days(today(), 1)}
			).insert()
		other = make_user("sp.cb.other@example.com", ("customer_followup",))
		with self.assertRaises(frappe.PermissionError):
			self.as_user(other, cb.open_today, COMPANY)
