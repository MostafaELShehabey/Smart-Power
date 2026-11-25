"""The lock on field entries (SP-109): a closed day is refused, asked for, reopened and listed."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate, today

from smart_power.dashboards.cards import entries_locking
from smart_power.rules import RuleBlocked
from smart_power.sp_core.inbox import act
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import field_entry as fe
from smart_power.sp_winch import field_lock as lock
from smart_power.tests.test_field_entry import list_value
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule, set_setting
from smart_power.www.sp_field import get_context

load_erpnext_test_data()

COMPANY = "_Test Company"
N = 3
AMOUNT = 100


class TestFieldLock(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		seed_centers(COMPANY)
		cls.driver = make_user("sp.lock.driver@example.com", ("winch_operator",))
		cls.other = make_user("sp.lock.other@example.com", ("winch_operator",))
		cls.amira = make_user("sp.lock.amira@example.com", ("project_manager",))
		cls.fuel = list_value("Field Expense", "FUEL")
		plate = "SP109-WINCH"
		if not frappe.db.exists("Vehicle", plate):
			frappe.get_doc(
				{"doctype": "Vehicle", "license_plate": plate, "sp_vehicle_type": "Winch", "company": COMPANY}
			).insert()
		cls.vehicle = plate

	def setUp(self):
		set_setting(account_map=[], field_entry_lock_days=N)
		fe.seed_account_map(COMPANY)
		set_rule("field_entry_day_locked", "Block")
		frappe.db.delete("SP Reopen Request", {"vehicle": self.vehicle})
		frappe.db.delete("SP Field Entry", {"vehicle": self.vehicle})
		self.addCleanup(frappe.set_user, "Administrator")

	def values(self, day, **more):
		return {
			"entry_kind": "Expense",
			"vehicle": self.vehicle,
			"work_date": day,
			"expense_type": self.fuel,
			"amount": AMOUNT,
			"paid_from": "Custody",
			**more,
		}

	def log(self, day, user=None, **more):
		frappe.set_user(user or self.driver)
		try:
			result = fe.save_entry(self.values(day, **more))
		finally:
			frappe.set_user("Administrator")
		return result

	def old_entry(self, days_ago):
		"""An entry logged in time, whose day has since passed."""
		name = self.log(today())
		frappe.db.set_value(fe.ENTRY, name, "work_date", add_days(today(), -days_ago))
		return frappe.get_doc(fe.ENTRY, name)

	def edit(self, name, user=None):
		frappe.set_user(user or self.driver)
		try:
			doc = frappe.get_doc(fe.ENTRY, name)
			doc.note = "changed"
			doc.save()
		finally:
			frappe.set_user("Administrator")

	def ask(self, day, user=None):
		frappe.set_user(user or self.driver)
		try:
			return lock.ask_to_reopen(self.vehicle, str(day), "The receipt came late")
		finally:
			frappe.set_user("Administrator")

	def test_an_entry_is_open_for_the_lock_days_and_refused_after(self):
		self.assertTrue(self.log(add_days(today(), -N)))
		with self.assertRaises(RuleBlocked) as refused:
			self.log(add_days(today(), -(N + 1)))
		self.assertIn("Day locked", str(refused.exception))
		hits = frappe.local.response.get("sp_rule_hits")
		self.assertEqual(hits[0]["code"], "DAY_LOCKED")

	def test_a_locked_entry_cannot_be_changed(self):
		doc = self.old_entry(N + 1)
		with self.assertRaises(RuleBlocked):
			self.edit(doc.name)

	def test_an_entry_cannot_leave_a_locked_day_for_an_open_one(self):
		doc = self.old_entry(N + 1)
		doc.work_date = today()
		with self.assertRaises(RuleBlocked):
			doc.save()

	def test_an_approved_reopening_gives_a_new_window_and_is_listed(self):
		doc = self.old_entry(N + 1)
		lock.lock_entries()
		self.assertEqual(frappe.db.get_value(fe.ENTRY, doc.name, "status"), "Locked")
		request = self.ask(doc.work_date)
		frappe.set_user(self.amira)
		task = frappe.db.get_value(
			"SP Task", {"reference_name": request, "assigned_to": self.amira, "status": "Open"}
		)
		self.assertIn("The receipt came late", frappe.db.get_value("SP Task", task, "subject"))
		act(task, "approve")
		frappe.set_user("Administrator")
		row = frappe.get_doc(lock.REQUEST, request)
		self.assertEqual((row.status, row.approved_by), ("Approved", self.amira))
		self.assertEqual(getdate(row.reopen_until), getdate(add_days(nowdate(), N)))
		self.edit(doc.name)
		saved = frappe.get_doc(fe.ENTRY, doc.name)
		self.assertEqual((saved.status, saved.reopened, saved.note), ("Logged", 1, "changed"))
		self.assertTrue(
			frappe.db.exists("SP Review Item", {"category": "Late Entry", "reference_name": request})
		)
		self.assertFalse(frappe.db.exists("SP Task", {"reference_name": request, "status": "Open"}))

	def test_the_new_window_ends_too(self):
		doc = self.old_entry(N + 2)
		request = self.ask(doc.work_date)
		frappe.set_user(self.amira)
		lock.approve(request)
		frappe.set_user("Administrator")
		frappe.db.set_value(lock.REQUEST, request, "reopen_until", add_days(nowdate(), -1))
		with self.assertRaises(RuleBlocked):
			self.edit(doc.name)

	def test_a_reopening_covers_only_that_vehicle_and_day(self):
		doc = self.old_entry(N + 1)
		request = self.ask(doc.work_date)
		frappe.set_user(self.amira)
		lock.approve(request)
		frappe.set_user("Administrator")
		self.assertTrue(lock.is_locked(self.vehicle, add_days(doc.work_date, -1)))

	def test_a_rejected_request_keeps_the_day_locked_and_tells_why(self):
		doc = self.old_entry(N + 1)
		request = self.ask(doc.work_date)
		frappe.set_user(self.amira)
		with self.assertRaises(frappe.MandatoryError):
			lock.reject(request, " ")
		lock.reject(request, "No receipt")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(lock.REQUEST, request, "status"), "Rejected")
		self.assertTrue(lock.is_locked(self.vehicle, doc.work_date))
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": self.driver, "document_name": request})
		)

	def test_asking_needs_a_locked_day_and_a_reason_and_is_asked_once(self):
		day = add_days(today(), -(N + 1))
		frappe.set_user(self.driver)
		with self.assertRaises(frappe.MandatoryError):
			lock.ask_to_reopen(self.vehicle, day, " ")
		with self.assertRaises(frappe.ValidationError):
			lock.ask_to_reopen(self.vehicle, today(), "Not locked")
		frappe.set_user("Administrator")
		self.assertEqual(self.ask(day), self.ask(day))

	def test_a_driver_with_nothing_logged_that_day_sees_the_lock_and_asks(self):
		# BUG-17: the light page offered "ask" only on an entry already logged that day
		day = add_days(today(), -(N + 1))
		with self.assertRaises(RuleBlocked):
			self.log(day)
		frappe.set_user(self.driver)
		try:
			state = lock.lock_state(self.vehicle, str(day))
			self.assertEqual((state["locked"], state["blocked"], state["request"]), (True, True, None))
			request = lock.ask_to_reopen(self.vehicle, str(day), "Fuel receipt found")
			self.assertEqual(lock.lock_state(self.vehicle, str(day))["request"], request)
		finally:
			frappe.set_user("Administrator")

	def test_only_the_projects_manager_or_admin_decides(self):
		request = self.ask(add_days(today(), -(N + 1)))
		frappe.set_user(self.other)
		with self.assertRaises(frappe.PermissionError):
			lock.approve(request)

	def test_an_offline_entry_for_a_locked_day_becomes_one_fix_it_task(self):
		day = add_days(today(), -(N + 2))
		sent = {"client_uuid": "sp109-late", "device_time": f"{day} 10:00:00"}
		first = self.log(day, **sent)
		second = self.log(day, **sent)
		self.assertEqual((first["refused"], first["code"]), (1, "DAY_LOCKED"))
		self.assertEqual(first["task"], second["task"])
		self.assertFalse(frappe.db.exists(fe.ENTRY, {"client_uuid": "sp109-late"}))
		task = frappe.get_doc("SP Task", first["task"])
		self.assertEqual((task.task_type, task.assigned_to), ("Fix Rejected Sync", self.driver))

	def test_entries_locking_next_are_announced_to_their_operator(self):
		doc = self.old_entry(N)
		self.assertEqual(lock.locking_soon(self.driver), [doc.name])
		self.assertEqual(lock.locking_soon(self.other), [])
		self.assertEqual(lock.locking_soon(self.amira), [doc.name])
		lock.lock_entries()
		self.assertEqual(frappe.db.get_value(fe.ENTRY, doc.name, "status"), "Logged")
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": self.driver, "document_name": doc.name})
		)

	def test_the_admin_can_soften_the_rule_and_a_late_entry_is_still_listed(self):
		set_rule("field_entry_day_locked", "Warn")
		name = self.log(add_days(today(), -(N + 1)))
		self.assertTrue(
			frappe.db.exists("SP Review Item", {"category": "Late Entry", "reference_name": name})
		)
		set_rule("field_entry_day_locked", "Off")
		self.assertTrue(self.log(add_days(today(), -(N + 2))))
		self.assertEqual(lock.lock_entries(), [])

	def test_a_request_is_seen_by_who_asked_and_the_office(self):
		self.ask(add_days(today(), -(N + 1)))
		self.assertIn(self.other, lock.query_conditions(self.other))
		self.assertEqual(lock.query_conditions(self.amira), "")

	def test_the_operator_page_shows_locks_and_what_locks_next(self):
		locked, soon = self.old_entry(N + 1), self.old_entry(N)
		frappe.set_user(self.driver)
		context = frappe._dict()
		get_context(context)
		marks = {e["name"]: e["locked"] for e in context.entries}
		self.assertEqual((marks[locked.name], marks[soon.name]), (True, False))
		self.assertEqual(context.locking, 1)

	def test_the_home_card_counts_what_locks_next(self):
		doc = self.old_entry(N)
		card = entries_locking(self.amira)
		self.assertEqual(card["value"], 1)
		self.assertEqual(card["route_options"]["name"], ["in", [doc.name]])
