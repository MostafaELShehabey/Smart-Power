"""Winch receipts (SP-112): money collected is allocated to jobs, oldest first, and each job knows
whether it is Open, Partial, Paid or Discounted."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_finance.accounts import TRANSIT, holder_account, seed_accounts
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import field_entry as fe
from smart_power.sp_winch import receipts as wr
from smart_power.tests.test_field_entry import balance, list_value
from smart_power.tests.test_purchase_orders import station
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
FIRST, SECOND, RECEIVED, LEFT = 20000, 15000, 25000, 10000
DISCOUNT, STATION_JOB = 500, 3000
PHONE, OTHER_PHONE = "01001120112", "01001120113"


class TestWinchReceipts(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		seed_centers(COMPANY)
		cls.operator = make_user("sp.wr.operator@example.com", ("winch_operator",))
		cls.manager = make_user("sp.wr.manager@example.com", ("winch_manager",))
		cls.job_type = list_value("Job Type", "PUMP_DOWN")
		cls.cash = list_value("Payment Method", "CASH")
		cls.instapay = list_value("Payment Method", "INSTAPAY")
		cls.official = frappe.db.get_value("Account", {"company": COMPANY, "sp_account_kind": "Official"})
		plate = "SP112-WINCH"
		if not frappe.db.exists("Vehicle", plate):
			frappe.get_doc(
				{"doctype": "Vehicle", "license_plate": plate, "sp_vehicle_type": "Winch", "company": COMPANY}
			).insert()
		cls.vehicle = plate

	def setUp(self):
		set_setting(
			account_map=[],
			field_entry_lock_days=3,
			winch_discount_role=None,
			winch_internal_revenue="On the job",
		)
		fe.seed_account_map(COMPANY)
		frappe.db.delete(wr.RECEIPT)
		frappe.db.delete(wr.ALLOCATION)
		frappe.db.delete(fe.ENTRY, {"vehicle": self.vehicle})
		self.addCleanup(frappe.set_user, "Administrator")

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def job(self, amount, days_ago=0, phone=PHONE, **values):
		name = self.as_user(
			self.operator,
			fe.save_entry,
			{
				"entry_kind": "Job",
				"vehicle": self.vehicle,
				"work_date": str(add_days(today(), -days_ago)),
				"job_type": self.job_type,
				"for_kind": "Outside",
				"customer_name": "SP112 Farmer",
				"customer_phone": phone,
				"place": "SP112 Farm",
				"agreed_amount": amount,
				**values,
			},
		)
		return frappe.get_doc(fe.ENTRY, name)

	def receipt(self, amount, customer, user=None, rows=None, **values):
		doc = frappe.get_doc(
			{
				"doctype": wr.RECEIPT,
				"customer": customer,
				"amount": amount,
				"method": self.cash,
				"allocations": rows or [],
				**values,
			}
		)
		self.as_user(user or self.manager, doc.insert)
		return doc

	def state(self, name):
		return frappe.db.get_value(
			fe.ENTRY, name, ["payment_status", "paid_amount", "discount_amount", "outstanding_amount"]
		)

	def test_a_receipt_pays_the_oldest_jobs_first(self):
		first, second = self.job(FIRST, days_ago=2), self.job(SECOND, days_ago=1)
		self.assertEqual(first.customer, second.customer)
		self.assertEqual(self.state(first.name)[0], "Open")
		doc = self.receipt(RECEIVED, first.customer)
		self.assertEqual(
			[(r.job, flt(r.amount)) for r in doc.allocations],
			[(first.name, FIRST), (second.name, RECEIVED - FIRST)],
		)
		self.assertEqual(self.state(first.name), ("Paid", FIRST, 0, 0))
		self.assertEqual(self.state(second.name), ("Partial", RECEIVED - FIRST, 0, LEFT))
		transit = holder_account(self.manager, TRANSIT, COMPANY)
		self.assertEqual(balance(transit, voucher_no=("in", fe.postings(doc))), RECEIVED)

	def test_the_allocation_stays_editable(self):
		first, second = self.job(FIRST, days_ago=2), self.job(SECOND, days_ago=1)
		doc = self.receipt(SECOND, first.customer)
		self.assertEqual(self.state(first.name)[0], "Partial")
		doc.allocations = []
		doc.append("allocations", {"job": second.name, "amount": SECOND})
		self.as_user(self.manager, doc.save)
		self.assertEqual((self.state(first.name)[0], self.state(second.name)[0]), ("Open", "Paid"))
		self.as_user("Administrator", frappe.delete_doc, wr.RECEIPT, doc.name)
		self.assertEqual(self.state(second.name)[0], "Open")
		self.assertFalse(fe.postings(doc))

	def test_a_job_is_paid_no_more_than_is_open(self):
		first = self.job(FIRST)
		other = self.job(SECOND, phone=OTHER_PHONE)
		with self.assertRaises(frappe.ValidationError):
			self.receipt(FIRST + 1, first.customer, rows=[{"job": first.name, "amount": FIRST + 1}])
		with self.assertRaises(frappe.ValidationError):
			self.receipt(SECOND, first.customer, rows=[{"job": other.name, "amount": SECOND}])
		self.receipt(FIRST, first.customer)
		first.reload()
		first.agreed_amount = FIRST - 1
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.operator, first.save)

	def test_more_than_the_jobs_stays_on_the_customer(self):
		first = self.job(FIRST)
		doc = self.receipt(RECEIVED, first.customer)
		self.assertEqual((flt(doc.allocated_amount), flt(doc.unallocated_amount)), (FIRST, RECEIVED - FIRST))

	def test_a_discount_needs_its_reason_and_the_right_role(self):
		first = self.job(FIRST)
		rows = [
			{
				"job": first.name,
				"amount": FIRST - DISCOUNT,
				"discount": DISCOUNT,
				"discount_reason": "Old customer",
			}
		]
		with self.assertRaises(frappe.PermissionError):
			self.receipt(FIRST - DISCOUNT, first.customer, rows=rows)
		set_setting(winch_discount_role="SP Winch Manager")
		with self.assertRaises(frappe.MandatoryError):
			self.receipt(FIRST - DISCOUNT, first.customer, rows=[{**rows[0], "discount_reason": ""}])
		doc = self.receipt(FIRST - DISCOUNT, first.customer, rows=rows)
		self.assertEqual(self.state(first.name), ("Discounted", FIRST - DISCOUNT, DISCOUNT, 0))
		discounts = fe._account(COMPANY, fe.DISCOUNT_ACCOUNT)
		self.assertEqual(balance(discounts, voucher_no=("in", fe.postings(doc))), DISCOUNT)

	def test_money_into_an_official_account_waits_for_the_admin(self):
		first = self.job(FIRST)
		doc = self.receipt(
			FIRST, first.customer, method=self.instapay, to_account=self.official, photo="/files/sp112.jpg"
		)
		self.assertEqual(
			frappe.db.get_value(fe.TRANSFER, doc.transfer, ["status", "to_account"]),
			("Pending", self.official),
		)

	def test_the_booking_and_the_field_review_follow(self):
		booking = frappe.get_doc(
			{
				"doctype": "SP Vehicle Booking",
				"for_kind": "Outside",
				"customer_name": "SP112 Booked",
				"customer_phone": PHONE,
				"vehicle": self.vehicle,
				"job_type": self.job_type,
				"place": "SP112 Farm",
				"planned_date": today(),
				"agreed_amount": FIRST,
			}
		).insert()
		job = self.job(FIRST, booking=booking.name)
		self.assertIn(
			"unpaid",
			{f["flag"] for f in frappe.parse_json(frappe.db.get_value(fe.ENTRY, job.name, "review_flags"))},
		)
		self.receipt(FIRST, job.customer)
		self.assertEqual(frappe.db.get_value("SP Vehicle Booking", booking.name, "payment_status"), "Paid")
		flags = frappe.parse_json(frappe.db.get_value(fe.ENTRY, job.name, "review_flags") or "[]")
		self.assertNotIn("unpaid", {f["flag"] for f in flags})

	def station_job(self):
		name = self.as_user(
			self.operator,
			fe.save_entry,
			{
				"entry_kind": "Job",
				"vehicle": self.vehicle,
				"work_date": today(),
				"job_type": self.job_type,
				"for_kind": "Station",
				"station": station().name,
				"agreed_amount": STATION_JOB,
			},
		)
		return frappe.get_doc(fe.ENTRY, name)

	def test_a_station_job_is_open_until_the_admin_confirms_it(self):
		job = self.station_job()
		self.assertEqual(self.state(job.name)[0], "Open")
		self.assertTrue(fe.postings(job))
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.manager, wr.confirm_jobs, [job.name])
		wr.confirm_jobs([job.name])
		self.assertEqual(self.state(job.name)[0], "Paid")
		self.assertEqual(len(fe.postings(job)), 1)

	def test_charged_on_confirmation_when_the_setting_says_so(self):
		set_setting(winch_internal_revenue="On confirmation")
		job = self.station_job()
		self.assertFalse(fe.postings(job))
		wr.confirm_jobs([job.name])
		self.assertEqual(len(fe.postings(job)), 1)
		self.assertEqual(self.state(job.name)[0], "Paid")
