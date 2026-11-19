"""Winch receivables (SP-112): who owes since when, follow-up notes, the debt age alert and the
old-debt warning on a new booking."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, today

from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import field_entry as fe
from smart_power.sp_winch import receipts as wr
from smart_power.sp_winch import receivables as rc
from smart_power.tests.test_field_entry import list_value
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
AGE, AMOUNT, PAID = 3, 4000, 1000
PHONE = "01001120114"


class TestWinchReceivables(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		seed_centers(COMPANY)
		cls.operator = make_user("sp.wrv.operator@example.com", ("winch_operator",))
		cls.manager = make_user("sp.wrv.manager@example.com", ("winch_manager",))
		cls.admin = make_user("sp.wrv.admin@example.com", ("admin",))
		cls.job_type = list_value("Job Type", "PUMP_DOWN")
		cls.cash = list_value("Payment Method", "CASH")
		plate = "SP112-JUMBO"
		if not frappe.db.exists("Vehicle", plate):
			frappe.get_doc(
				{"doctype": "Vehicle", "license_plate": plate, "sp_vehicle_type": "Jumbo", "company": COMPANY}
			).insert()
		cls.vehicle = plate

	def setUp(self):
		set_setting(account_map=[], field_entry_lock_days=0, winch_debt_age_months=AGE)
		fe.seed_account_map(COMPANY)
		set_rule("winch_old_debt", "Warn")
		frappe.db.delete(wr.RECEIPT)
		frappe.db.delete(fe.ENTRY, {"vehicle": self.vehicle})
		self.addCleanup(frappe.set_user, "Administrator")

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def job(self, months_ago=0, received=0):
		name = self.as_user(
			self.operator,
			fe.save_entry,
			{
				"entry_kind": "Job",
				"vehicle": self.vehicle,
				"work_date": str(add_months(today(), -months_ago)),
				"job_type": self.job_type,
				"for_kind": "Outside",
				"customer_name": "SP112 Debtor",
				"customer_phone": PHONE,
				"place": "SP112 Farm",
				"agreed_amount": AMOUNT,
				"received_now": received,
				"received_method": self.cash if received else None,
			},
		)
		return frappe.get_doc(fe.ENTRY, name)

	def mine(self, data):
		return next(r for r in data["customers"] if r["phone"] == PHONE)

	def test_the_list_shows_who_owes_since_when_and_the_last_note(self):
		old, recent = self.job(months_ago=AGE + 1), self.job(received=PAID)
		self.as_user(self.manager, rc.add_note, old.customer, "Pays after the harvest")
		row = self.mine(self.as_user(self.manager, rc.receivables))
		self.assertEqual([j["name"] for j in row["jobs"]], [old.name, recent.name])
		self.assertEqual(row["outstanding"], AMOUNT * 2 - PAID)
		self.assertTrue(row["old"])
		self.assertEqual(row["last_note"]["note"], "Pays after the harvest")
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.operator, rc.receivables)

	def test_an_old_debt_is_announced_once(self):
		old = self.job(months_ago=AGE + 1)
		self.job()
		self.assertEqual(rc.check_old_debts(), [old.name])
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": self.manager, "document_name": old.name})
		)
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": self.admin, "document_name": old.name})
		)
		self.assertEqual(rc.check_old_debts(), [])
		set_setting(winch_debt_age_months=0)
		self.assertEqual(rc._old_jobs(), [])

	def test_a_new_booking_for_an_old_debtor_warns(self):
		self.job(months_ago=AGE + 1)
		booking = frappe.get_doc(
			{
				"doctype": "SP Vehicle Booking",
				"for_kind": "Outside",
				"customer_name": "SP112 Debtor",
				"customer_phone": PHONE,
				"vehicle": self.vehicle,
				"job_type": self.job_type,
				"place": "SP112 Farm",
				"planned_date": today(),
				"agreed_amount": AMOUNT,
			}
		)
		booking.insert()
		self.assertTrue(
			frappe.db.exists(
				"SP Rule Hit", {"reference_name": booking.name, "rule": "winch_old_debt", "outcome": "Warned"}
			)
		)
		set_rule("winch_old_debt", "Block")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({**booking.as_dict(), "name": None, "doctype": "SP Vehicle Booking"}).insert()

	def test_paid_jobs_leave_the_list(self):
		job = self.job()
		frappe.get_doc(
			{"doctype": wr.RECEIPT, "customer": job.customer, "amount": AMOUNT, "method": self.cash}
		).insert()
		self.assertFalse([r for r in rc.receivables()["customers"] if r["phone"] == PHONE])
