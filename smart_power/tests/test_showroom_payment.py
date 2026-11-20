"""SH5 payment on a station at the showroom (SP-103): found by mobile, credited to the station, not
to showroom sales, pending the admin, and the collection owner is told."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_finance import showroom_payment as sp
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.customer_payment import confirm
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import ensure_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_customer_payment import account
from smart_power.tests.test_field_entry import balance, list_value
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
AGREED, HALF, PAID = 200000, 100000, 10000
MOBILE = "01001030103"


class TestShowroomPayment(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		cls.cashier = make_user("sp.sh5.cashier@example.com", ("showroom_cashier",))
		cls.other = make_user("sp.sh5.sales@example.com", ("showroom_sales",))
		cls.amira = make_user("sp.sh5.amira@example.com", ("project_manager", "collection_officer"))
		cls.admin = make_user("sp.sh5.admin@example.com", ("admin",))
		cls.cash = list_value("Payment Method", "CASH")
		cls.instapay = list_value("Payment Method", "INSTAPAY")
		cls.official = account("SP SH5 InstaPay", "Bank", "Official", account_type="Bank")

	def setUp(self):
		set_setting(large_payment_threshold=0)
		q = make_quotation(rate=AGREED, valid_days=3, save=False)
		q.insert()
		q.set(
			"payment_schedule",
			[
				{"due_date": today(), "invoice_portion": 50, "payment_amount": HALF},
				{"due_date": add_days(today(), 30), "invoice_portion": 50, "payment_amount": HALF},
			],
		)
		q.save()
		q.submit()
		approve_version(q.name)
		result = ensure_contract(q.sp_case)
		frappe.get_doc("Sales Order", result["sales_order"]).submit()
		self.station = result["station"]
		frappe.db.set_value("SP Station", self.station, "collection_owner", self.amira)
		self.customer = frappe.db.get_value("SP Station", self.station, "customer")
		frappe.db.set_value("Customer", self.customer, "sp_mobile", MOBILE)
		self.box = frappe.db.get_value("Account", {"company": COMPANY, "account_name": "Showroom Safe"})
		frappe.defaults.set_user_default("Company", COMPANY, self.cashier)
		self.addCleanup(frappe.set_user, "Administrator")

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def test_the_cashier_finds_the_station_by_mobile_with_what_is_left(self):
		found = self.as_user(self.cashier, sp.find_station, MOBILE)
		row = next(r for r in found if r["station"] == self.station)
		self.assertEqual(row["remaining"], AGREED)
		self.assertEqual((row["next_due"]["left"], len(row["schedule"])), (HALF, 2))
		self.assertNotIn("agreed_amount", row)  # sale-price data only: what is owed, never costs
		self.assertEqual(self.as_user(self.cashier, sp.find_station, "01"), [])
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other, sp.find_station, MOBILE)

	def test_cash_at_the_showroom_is_pending_into_the_box_and_the_owner_is_told(self):
		name = self.as_user(
			self.cashier, sp.record, {"station": self.station, "amount": PAID, "method": self.cash}
		)
		doc = frappe.get_doc("SP Customer Payment", name)
		self.assertEqual((doc.status, doc.channel, doc.receiving_account), ("Pending", "Showroom", self.box))
		self.assertTrue(
			frappe.db.exists(
				"Notification Log",
				{"for_user": self.amira, "document_name": name, "sp_event": "showroom_payment"},
			)
		)
		self.assertTrue(frappe.db.exists("SP Task", {"reference_name": name, "status": "Open"}))
		self.assertEqual(flt(frappe.db.get_value("SP Station", self.station, "paid_amount")), 0)
		row = next(
			r for r in self.as_user(self.cashier, sp.find_station, MOBILE) if r["station"] == self.station
		)
		self.assertEqual(row["remaining"], AGREED - PAID)  # what is pending is not asked for again
		self.assertEqual([p.name for p in self.as_user(self.cashier, sp.today)], [name])

	def test_confirmed_it_credits_the_station_not_showroom_sales(self):
		name = self.as_user(
			self.cashier, sp.record, {"station": self.station, "amount": PAID, "method": self.cash}
		)
		before = balance(self.box)
		self.as_user(self.admin, confirm, name)
		self.assertEqual(balance(self.box) - before, PAID)
		entry = frappe.db.get_value("SP Customer Payment", name, "payment_entry")
		pe = frappe.get_doc("Payment Entry", entry)
		self.assertEqual((pe.party_type, pe.party, pe.paid_to), ("Customer", self.customer, self.box))
		self.assertEqual(flt(frappe.db.get_value("SP Station", self.station, "paid_amount")), PAID)
		income = frappe.get_all(
			"GL Entry",
			{"voucher_no": entry, "is_cancelled": 0, "account": ("like", "%Sales%")},
			pluck="name",
		)
		self.assertEqual(income, [])

	def test_other_methods_go_to_an_official_account_with_the_photo(self):
		with self.assertRaises(frappe.ValidationError):
			self.as_user(
				self.cashier,
				sp.record,
				{
					"station": self.station,
					"amount": PAID,
					"method": self.instapay,
					"receiving_account": self.official,
				},
			)
		name = self.as_user(
			self.cashier,
			sp.record,
			{
				"station": self.station,
				"amount": PAID,
				"method": self.instapay,
				"receiving_account": self.official,
				"receipt_photo": "/files/sh5.jpg",
			},
		)
		self.assertEqual(frappe.db.get_value("SP Customer Payment", name, "receiving_account"), self.official)

	def test_only_the_showroom_cashier_uses_the_box(self):
		frappe.set_user(self.amira)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SP Customer Payment",
					"station": self.station,
					"amount": PAID,
					"method": self.cash,
					"receiving_account": self.box,
					"channel": "Showroom",
				}
			)
			with self.assertRaises(frappe.PermissionError):
				doc.insert()
		finally:
			frappe.set_user("Administrator")

	def test_the_sh5_page_is_for_the_showroom_cashier(self):
		page = frappe.get_doc("Page", "sp-showroom-payment")
		self.assertEqual({r.role for r in page.roles}, {"SP Showroom Cashier", "SP Admin", "System Manager"})
