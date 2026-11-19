"""RV1 field review (SP-110): entries by day with flags, completed, reviewed, flagged and reopened."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.rules import RuleBlocked
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import field_entry as fe
from smart_power.sp_winch import review as rv
from smart_power.tests.test_bookings import employee
from smart_power.tests.test_field_entry import list_value
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
N = 3
BOOKED, AGREED, CASH_IN, PART = 3000, 2500, 1000, 100
PHONE = "01001100110"
NO_LIMITS = json.dumps({"average_factor": 1.5, "min_entries": 3, "by_type": {}})


class TestFieldReview(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		seed_centers(COMPANY)
		cls.driver = make_user("sp.rv.driver@example.com", ("winch_operator",))
		cls.amira = make_user("sp.rv.amira@example.com", ("project_manager",))
		cls.reviewer = make_user("sp.rv.reviewer@example.com", ("winch_reviewer",))
		cls.admin = make_user("sp.rv.admin@example.com", ("admin",))
		employee(cls.driver, "SP110 Driver")
		cls.job_type = list_value("Job Type", "PUMP_DOWN")
		cls.parts = list_value("Field Expense", "SP110_PARTS")
		cls.cash = list_value("Payment Method", "CASH")
		plate = "SP110-WINCH"
		if not frappe.db.exists("Vehicle", plate):
			frappe.get_doc(
				{"doctype": "Vehicle", "license_plate": plate, "sp_vehicle_type": "Winch", "company": COMPANY}
			).insert()
		cls.vehicle = plate

	def setUp(self):
		set_setting(account_map=[], field_entry_lock_days=N)
		fe.seed_account_map(COMPANY)
		set_rule("field_entry_day_locked", "Block")
		set_rule("field_expense_unusual", "Warn", limits=NO_LIMITS)
		frappe.db.delete("SP Field Review")
		frappe.db.delete("SP Reopen Request", {"vehicle": self.vehicle})
		frappe.db.delete("SP Field Entry", {"vehicle": self.vehicle})
		self.addCleanup(frappe.set_user, "Administrator")

	def log(self, day=None, **values):
		frappe.set_user(self.driver)
		try:
			name = fe.save_entry({"vehicle": self.vehicle, "work_date": str(day or today()), **values})
		finally:
			frappe.set_user("Administrator")
		return frappe.get_doc(fe.ENTRY, name)

	def expense(self, day=None, **values):
		return self.log(
			day,
			**{
				"entry_kind": "Expense",
				"expense_type": self.parts,
				"amount": PART,
				"paid_from": "Custody",
				"photo": "/files/sp110-receipt.jpg",
				**values,
			},
		)

	def outside_job(self, day=None, **values):
		return self.log(
			day,
			**{
				"entry_kind": "Job",
				"job_type": self.job_type,
				"for_kind": "Outside",
				"customer_name": "SP110 Farmer",
				"customer_phone": PHONE,
				"place": "SP110 Farm",
				"agreed_amount": AGREED,
				"received_now": CASH_IN,
				"received_method": self.cash,
				**values,
			},
		)

	def flags(self, name):
		return {f["flag"]: rv.detail(f) for f in rv.flags_of(frappe.get_doc(fe.ENTRY, name))}

	def page(self, user=None, **filters):
		frappe.set_user(user or self.amira)
		try:
			return rv.entries(vehicle=self.vehicle, **filters)
		finally:
			frappe.set_user("Administrator")

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def test_a_job_agreed_below_its_booking_is_flagged(self):
		booking = frappe.get_doc(
			{
				"doctype": "SP Vehicle Booking",
				"for_kind": "Outside",
				"customer_name": "SP110 Booked",
				"customer_phone": PHONE,
				"vehicle": self.vehicle,
				"job_type": self.job_type,
				"place": "SP110 Farm",
				"planned_date": today(),
				"agreed_amount": BOOKED,
			}
		).insert()
		doc = self.log(
			entry_kind="Job",
			booking=booking.name,
			agreed_amount=AGREED,
			received_now=AGREED,
			received_method=self.cash,
		)
		shown = self.page()["days"][0]["vehicles"][0]["entries"][0]
		self.assertEqual(shown["name"], doc.name)
		flag = next(f for f in shown["flags"] if f["flag"] == rv.AMOUNT_DIFFERS)
		self.assertEqual(flag["label"], "Amount differs from the booking")
		self.assertIn("booked", flag["detail"])
		self.assertNotIn(rv.UNPAID, self.flags(doc.name))

	def test_unpaid_until_the_rest_is_received(self):
		job = self.outside_job()
		self.assertIn(rv.UNPAID, self.flags(job.name))
		self.log(
			entry_kind="Money",
			money_kind="Received",
			related_job=job.name,
			amount=AGREED - CASH_IN,
			received_method=self.cash,
		)
		self.assertNotIn(rv.UNPAID, self.flags(job.name))

	def test_entered_more_than_a_day_late(self):
		self.assertIn(rv.LATE, self.flags(self.expense(add_days(today(), -2)).name))
		self.assertNotIn(rv.LATE, self.flags(self.expense(add_days(today(), -1)).name))

	def test_an_expense_far_above_its_average_or_threshold(self):
		for _i in range(3):
			self.assertNotIn(rv.UNUSUAL, self.flags(self.expense().name))
		self.assertIn(rv.UNUSUAL, self.flags(self.expense(amount=PART * 2).name))
		set_rule("field_expense_unusual", "Warn", limits=json.dumps({"by_type": {"SP110_PARTS": PART / 2}}))
		self.assertIn(rv.UNUSUAL, self.flags(self.expense().name))
		set_rule("field_expense_unusual", "Off")
		self.assertNotIn(rv.UNUSUAL, self.flags(self.expense(amount=PART * 2).name))

	def test_cash_still_held_past_its_limit(self):
		set_setting(cash_held_limit_days=1)
		job = self.outside_job(add_days(today(), -N))
		self.assertIn(rv.CASH_HELD, self.flags(job.name))
		set_setting(cash_held_limit_days=N + 1)
		rv.refresh_flags()
		self.assertNotIn(rv.CASH_HELD, self.flags(job.name))

	def test_completing_a_missing_detail_with_a_reason(self):
		doc = self.expense(photo=None)
		self.assertIn(rv.MISSING, self.flags(doc.name))
		with self.assertRaises(frappe.MandatoryError):
			self.as_user(self.amira, rv.complete, doc.name, {"photo": "/files/sp110.jpg"}, "")
		self.as_user(
			self.amira, rv.complete, doc.name, {"photo": "/files/sp110.jpg"}, "Receipt sent on WhatsApp"
		)
		self.assertNotIn(rv.MISSING, self.flags(doc.name))
		row = frappe.get_doc(rv.REVIEW, {"field_entry": doc.name})
		self.assertEqual(
			(row.action, row.note, row.reviewed_by), ("Completed", "Receipt sent on WhatsApp", self.amira)
		)
		self.assertEqual(row.flag, rv.MISSING)
		self.assertTrue(frappe.db.exists("SP Review Item", {"category": "Edit", "reference_name": doc.name}))

	def test_a_locked_day_is_reopened_before_it_is_completed(self):
		doc = self.expense(photo=None)
		day = add_days(today(), -(N + 1))
		frappe.db.set_value(fe.ENTRY, doc.name, "work_date", day)
		with self.assertRaises(RuleBlocked):
			self.as_user(self.amira, rv.complete, doc.name, {"photo": "/files/sp110.jpg"}, "Receipt found")
		asked = self.as_user(self.reviewer, rv.reopen_day, self.vehicle, str(day), "Receipt found")
		self.assertEqual(asked["status"], "Open")
		reopened = self.as_user(self.amira, rv.reopen_day, self.vehicle, str(day), "Receipt found")
		self.assertEqual((reopened["request"], reopened["status"]), (asked["request"], "Approved"))
		self.as_user(self.amira, rv.complete, doc.name, {"photo": "/files/sp110.jpg"}, "Receipt found")
		self.assertEqual(frappe.db.get_value(fe.ENTRY, doc.name, "reopened"), 1)
		self.assertEqual(frappe.db.count(rv.REVIEW, {"field_entry": doc.name, "action": "Reopened"}), 2)

	def test_flagged_abnormal_reaches_the_admin_with_the_note(self):
		doc = self.expense(amount=PART)
		item = self.as_user(self.amira, rv.flag_abnormal, doc.name, "Parts bought twice this week")
		row = frappe.get_doc("SP Review Item", item)
		self.assertEqual((row.category, row.reason), ("Abnormal", "Parts bought twice this week"))
		self.assertEqual(frappe.db.get_value(fe.ENTRY, doc.name, "status"), "Flagged")
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": self.admin, "document_name": doc.name})
		)

	def test_a_day_all_reviewed_gets_its_check(self):
		first, second = self.expense(), self.expense()
		self.assertFalse(self.page()["days"][0]["reviewed"])
		self.as_user(self.amira, rv.mark_reviewed, [first.name])
		self.assertFalse(self.page()["days"][0]["reviewed"])
		self.assertEqual(len(self.page(to_review=1)["days"][0]["vehicles"][0]["entries"]), 1)
		self.as_user(self.amira, rv.mark_reviewed, json.dumps([first.name, second.name]))
		day = self.page()["days"][0]
		self.assertTrue(day["reviewed"] and day["vehicles"][0]["reviewed"])
		saved = frappe.get_doc(fe.ENTRY, second.name)
		self.assertEqual((saved.status, saved.reviewed_by), ("Reviewed", self.amira))
		self.assertEqual(frappe.db.count(rv.REVIEW, {"action": "Reviewed"}), 2)

	def test_a_reviewed_entry_the_operator_changes_is_reviewed_again(self):
		doc = self.expense()
		self.as_user(self.amira, rv.mark_reviewed, [doc.name])
		frappe.set_user(self.driver)
		doc = frappe.get_doc(fe.ENTRY, doc.name)
		doc.amount = PART + 1
		doc.save()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(fe.ENTRY, doc.name, "status"), "Logged")

	def test_only_reviewers_review(self):
		self.expense()
		with self.assertRaises(frappe.PermissionError):
			self.page(user=self.driver)
		chips = {c["flag"]: c["count"] for c in self.page(user=self.reviewer)["flags"]}
		self.assertEqual(set(chips), set(rv.FLAGS))
