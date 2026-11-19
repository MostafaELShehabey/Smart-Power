"""The phone pages' server side (SP-180): options, my entries, changing one, and the lock."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, now_datetime, today

from smart_power.rules import RuleBlocked
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import field_entry as fe
from smart_power.sp_winch import field_lock as lock
from smart_power.sp_winch import field_page as fp
from smart_power.sp_winch import review as rv
from smart_power.tests.test_field_entry import list_value
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
N = 3
FUEL = 250


class TestFieldPagesApi(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		seed_centers(COMPANY)
		cls.driver = make_user("sp.fp.driver@example.com", ("driver",))
		cls.other = make_user("sp.fp.other@example.com", ("winch_operator",))
		cls.manager = make_user("sp.fp.manager@example.com", ("winch_manager",))
		cls.amira = make_user("sp.fp.amira@example.com", ("project_manager",))
		cls.job_type = list_value("Job Type", "PUMP_DOWN")
		cls.fuel = list_value("Field Expense", "FUEL")
		plate = "SP180-JUMBO"
		if not frappe.db.exists("Vehicle", plate):
			frappe.get_doc(
				{"doctype": "Vehicle", "license_plate": plate, "sp_vehicle_type": "Jumbo", "company": COMPANY}
			).insert()
		frappe.db.set_value("Vehicle", plate, "sp_driver_user", cls.driver)
		cls.vehicle = plate

	def setUp(self):
		set_setting(account_map=[], field_entry_lock_days=N)
		fe.seed_account_map(COMPANY)
		set_rule("field_entry_day_locked", "Block")
		frappe.db.delete("SP Reopen Request", {"vehicle": self.vehicle})
		frappe.db.delete(fe.ENTRY, {"vehicle": self.vehicle})
		self.addCleanup(frappe.set_user, "Administrator")

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def expense(self, day=None, user=None):
		return self.as_user(
			user or self.driver,
			fe.save_entry,
			{
				"entry_kind": "Expense",
				"vehicle": self.vehicle,
				"work_date": str(day or today()),
				"expense_type": self.fuel,
				"amount": FUEL,
				"paid_from": "Custody",
				"photo": "/files/sp180-receipt.jpg",
			},
		)

	def test_the_pickers_know_my_vehicle_and_the_lists(self):
		got = self.as_user(self.driver, fp.options)
		self.assertEqual(got["my_vehicle"], self.vehicle)
		self.assertIn(self.fuel, [r["name"] for r in got["expense_types"]])
		self.assertIn(self.job_type, [r["name"] for r in got["job_types"]])
		self.assertEqual((got["lock_days"], got["operators"]), (N, []))
		self.assertIn(self.driver, [u.name for u in self.as_user(self.manager, fp.options)["operators"]])

	def test_yesterdays_job_logged_today_reaches_the_field_review(self):
		before = now_datetime()
		name = self.as_user(
			self.driver,
			fe.save_entry,
			{
				"entry_kind": "Job",
				"vehicle": self.vehicle,
				"work_date": str(add_days(today(), -1)),
				"job_type": self.job_type,
				"for_kind": "Internal center",
				"internal_center": frappe.get_cached_value("Company", COMPANY, "cost_center"),
				"place": "SP180 Store",
				"agreed_amount": 0,
			},
		)
		doc = frappe.get_doc(fe.ENTRY, name)
		self.assertEqual(getdate(doc.work_date), getdate(add_days(today(), -1)))
		self.assertGreaterEqual(doc.entry_time, before.replace(microsecond=0))
		self.assertEqual(doc.logged_by, self.driver)
		day = self.as_user(self.amira, rv.entries, vehicle=self.vehicle)["days"][0]
		self.assertEqual(day["vehicles"][0]["entries"][0]["name"], name)

	def test_my_entries_can_be_changed_while_the_day_is_open(self):
		name = self.expense()
		self.assertEqual(self.as_user(self.driver, fp.entry, name)["locked"], False)
		self.as_user(self.driver, fp.update_entry, name, {"amount": FUEL + 50, "note": "two receipts"})
		self.assertEqual(frappe.db.get_value(fe.ENTRY, name, "amount"), FUEL + 50)
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.driver, fp.update_entry, name, {"client_uuid": "x"})
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other, fp.entry, name)

	def test_a_locked_entry_is_read_only_and_asking_to_reopen_tells_the_reviewer(self):
		name = self.expense()
		day = add_days(today(), -(N + 1))
		frappe.db.set_value(fe.ENTRY, name, "work_date", day)
		shown = next(e for e in self.as_user(self.driver, fp.entries) if e["name"] == name)
		self.assertEqual((shown["locked"], shown["request"]), (True, None))
		self.assertTrue(self.as_user(self.driver, fp.entry, name)["locked"])
		with self.assertRaises(RuleBlocked):
			self.as_user(self.driver, fp.update_entry, name, {"amount": FUEL + 1})
		request = self.as_user(self.driver, lock.ask_to_reopen, self.vehicle, str(day), "Receipt came late")
		self.assertTrue(
			frappe.db.exists(
				"Notification Log",
				{"for_user": self.amira, "document_name": request, "sp_event": "reopen_asked"},
			)
		)
		shown = next(e for e in self.as_user(self.driver, fp.entries) if e["name"] == name)
		self.assertEqual(shown["request"], request)
