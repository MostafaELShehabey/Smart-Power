"""Postal cheque register (SP-118)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate, today

from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.cheques import check_due, mark_bounced, mark_collected, mark_deposited
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import ensure_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import (
	load_erpnext_test_data,
	make_quotation,
	make_user,
	set_setting,
	sign_contract,
)

load_erpnext_test_data()

COMPANY = "_Test Company"


class TestCheques(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)

	def setUp(self):
		set_setting(cheque_due_lead_days=7, cheque_auto_confirm=1)
		self.amira = make_user(
			"sp.chq.amira@example.com", ("project_manager", "collection_officer", "contract_manager")
		)
		self.admin = make_user("sp.chq.admin@example.com", ("admin",))
		q = make_quotation(rate=100000, valid_days=3, save=False)
		q.insert()
		q.set(
			"payment_schedule",
			[
				{"due_date": today(), "invoice_portion": 85, "payment_amount": 85000},
				{"due_date": add_days(today(), 7), "invoice_portion": 15, "payment_amount": 15000},
			],
		)
		q.save()
		q.submit()
		approve_version(q.name)
		frappe.set_user(self.amira)
		try:
			result = ensure_contract(q.sp_case)
		finally:
			frappe.set_user("Administrator")
		self.station = result["station"]
		self.so = frappe.get_doc("Sales Order", result["sales_order"])
		frappe.db.set_value("SP Station", self.station, "collection_owner", self.amira)

	def tearDown(self):
		frappe.set_user("Administrator")

	def cheque(self, due, amount=15000, no=None):
		return frappe.get_doc(
			{
				"doctype": "SP Cheque",
				"cheque_no": no or frappe.generate_hash(length=8),
				"amount": amount,
				"due_date": due,
				"bank_or_post": "مكتب بريد المنيا",
				"holder": self.amira,
				"station": self.station,
			}
		).insert()

	def alerts(self, name, user):
		return frappe.db.exists("Notification Log", {"document_name": name, "for_user": user})

	def test_seven_days_before_it_is_due_and_the_holder_and_admin_are_told(self):
		soon = self.cheque(add_days(today(), 7))
		later = self.cheque(add_days(today(), 8))
		self.assertIn(soon.name, check_due())
		self.assertEqual(frappe.db.get_value("SP Cheque", soon.name, "status"), "Due")
		self.assertEqual(frappe.db.get_value("SP Cheque", later.name, "status"), "Received")
		self.assertTrue(self.alerts(soon.name, self.amira))
		self.assertTrue(self.alerts(soon.name, self.admin))

	def test_collected_posts_a_confirmed_payment_to_the_post(self):
		chq = self.cheque(add_days(today(), 7))
		paid_before = flt(frappe.db.get_value("SP Station", self.station, "paid_amount"))
		frappe.set_user(self.amira)
		mark_deposited(chq.name)
		mark_collected(chq.name)
		frappe.set_user("Administrator")
		chq.reload()
		payment = frappe.get_doc("SP Customer Payment", chq.customer_payment)
		self.assertEqual((chq.status, payment.status, payment.cheque), ("Collected", "Confirmed", chq.name))
		post = frappe.db.get_value("Account", {"company": COMPANY, "account_name": "The Post"})
		pe = frappe.get_doc("Payment Entry", payment.payment_entry)
		self.assertEqual((pe.paid_to, flt(pe.paid_amount), pe.docstatus), (post, 15000, 1))
		self.assertEqual(
			flt(frappe.db.get_value("SP Station", self.station, "paid_amount")) - paid_before, 15000
		)

	def test_a_bounce_reverses_the_payment_and_the_station_owes_it_again(self):
		from smart_power.sp_stations.money import refresh

		# the contract: 15,000 due yesterday (this cheque), then 85,000 next month
		rows = frappe.get_all("Payment Schedule", {"parent": self.so.name}, pluck="name", order_by="idx asc")
		frappe.db.set_value(
			"Payment Schedule", rows[0], {"due_date": add_days(today(), -1), "payment_amount": 15000}
		)
		frappe.db.set_value(
			"Payment Schedule", rows[1], {"due_date": add_days(today(), 30), "payment_amount": 85000}
		)
		chq = self.cheque(add_days(today(), -1))
		frappe.set_user(self.amira)
		mark_collected(chq.name)
		frappe.set_user("Administrator")
		refresh(self.station)
		self.assertGreater(
			getdate(frappe.db.get_value("SP Station", self.station, "next_due_date")), getdate(today())
		)
		before = frappe.db.get_value(
			"SP Station", self.station, ["remaining_amount", "next_due_date"], as_dict=True
		)
		pe = frappe.db.get_value(
			"SP Customer Payment",
			frappe.db.get_value("SP Cheque", chq.name, "customer_payment"),
			"payment_entry",
		)
		frappe.set_user(self.amira)
		mark_bounced(chq.name, "مرتجع")
		frappe.set_user("Administrator")
		after = frappe.db.get_value(
			"SP Station", self.station, ["remaining_amount", "next_due_date"], as_dict=True
		)
		self.assertEqual(flt(after.remaining_amount) - flt(before.remaining_amount), 15000)
		self.assertEqual(frappe.db.get_value("Payment Entry", pe, "docstatus"), 2)  # reversed
		self.assertLess(getdate(after.next_due_date), getdate(today()))  # overdue again
		self.assertTrue(self.alerts(chq.name, self.amira))
		self.assertEqual(frappe.db.get_value("SP Cheque", chq.name, "status"), "Bounced")

	def test_the_contracts_cheques_join_the_register(self):
		self.so.append(
			"sp_cheques",
			{
				"cheque_no": "C-D1-1",
				"bank": "البريد",
				"due_date": add_days(today(), 30),
				"amount": 15000,
				"holder": self.amira,
			},
		)
		self.so.save()
		sign_contract(self.so)
		self.assertTrue(frappe.db.exists("SP Cheque", {"cheque_no": "C-D1-1", "station": self.station}))

	def test_moves_follow_the_order(self):
		chq = self.cheque(add_days(today(), 20))
		frappe.set_user(self.amira)
		try:
			from smart_power.sp_finance.cheques import mark_with_lawyer

			with self.assertRaises(frappe.ValidationError):
				mark_with_lawyer(chq.name)  # only after a bounce
		finally:
			frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			self.cheque(add_days(today(), 20), no=chq.cheque_no)  # the same cheque twice

	def test_the_admin_confirms_when_settings_say_so(self):
		set_setting(cheque_auto_confirm=0)
		chq = self.cheque(add_days(today(), 7))
		frappe.set_user(self.amira)
		mark_collected(chq.name)
		frappe.set_user("Administrator")
		payment = frappe.db.get_value(
			"SP Customer Payment", frappe.db.get_value("SP Cheque", chq.name, "customer_payment"), "status"
		)
		self.assertEqual(payment, "Pending")
