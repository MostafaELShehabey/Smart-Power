"""Stock counts (SP-94): count sheets on the admin's schedule, blind counts, and the admin's approval."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_stock import stock_count as sc
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_purchase_orders import COMPANY
from smart_power.tests.test_transfers import on_hand, stock
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

MC4 = "_Test SP94 MC4"
PANEL = "_Test SP94 Panel"


def issue(item, warehouse, qty):
	entry = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Issue",
			"purpose": "Material Issue",
			"company": COMPANY,
			"items": [{"item_code": item, "qty": qty, "s_warehouse": warehouse}],
		}
	).insert()
	entry.submit()


class TestStockCount(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		cls.main = wh.warehouse_of(COMPANY, wh.MAIN)
		cls.showroom = wh.warehouse_of(COMPANY, wh.SHOWROOM)
		cls.keeper = make_user("sp.cnt.gaber@example.com", ("main_store_keeper",))
		cls.admin = make_user("sp.cnt.admin@example.com", ("admin",))
		cls.other = make_user("sp.cnt.other@example.com", ("site_receiver",))
		make_item(MC4, is_stock_item=1)
		make_item(PANEL, is_stock_item=1)
		stock(MC4, cls.main, 50)
		stock(PANEL, cls.main, 5)

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def count_all(self, name, user, **counted):
		"""Count every line: the given items as stated, the others as the books hold them."""
		lines = [
			{
				"item_code": l.item_code,
				"counted_qty": counted.get(l.item_code, on_hand(l.item_code, self.main)),
			}
			for l in frappe.get_doc(sc.COUNT, name).lines
		]
		return self.as_user(user, sc.save_counts, name, lines)

	def test_a_short_count_goes_to_the_admin_and_posts_minus_two_on_approval(self):
		name = self.as_user(self.keeper, sc.start_count, self.main, 0)
		self.count_all(name, self.keeper, **{MC4: 48})
		result = self.as_user(self.keeper, sc.submit_count, name)
		self.assertEqual(result["status"], sc.SUBMITTED)
		line = next(l for l in frappe.get_doc(sc.COUNT, name).lines if l.item_code == MC4)
		self.assertEqual((line.system_qty, line.counted_qty, line.diff), (50, 48, -2))
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{
					"reference_name": name,
					"task_type": sc.TASK_DIFFERENCE,
					"assigned_to": self.admin,
					"status": "Open",
				},
			)
		)
		decided = self.as_user(self.admin, sc.approve_count, name, "تالف")
		moved = frappe.db.get_value(
			"Stock Reconciliation Item",
			{"parent": decided["stock_reconciliation"], "item_code": MC4},
			["current_qty", "qty", "quantity_difference"],
		)
		self.assertEqual(tuple(flt(v) for v in moved), (50, 48, -2))
		self.assertEqual(
			frappe.db.get_value("Stock Reconciliation", decided["stock_reconciliation"], "docstatus"), 1
		)
		self.assertEqual(on_hand(MC4, self.main), 48)
		doc = frappe.get_doc(sc.COUNT, name)
		self.assertEqual((doc.status, doc.reason, doc.approved_by), (sc.APPROVED, "تالف", self.admin))
		log = frappe.get_all("SP Audit Log", {"reference_name": name}, ["action", "user", "details"])
		self.assertEqual([(r.action, r.user) for r in log], [("Stock count approved", self.admin)])
		self.assertIn("تالف", log[0].details)
		self.assertFalse(
			frappe.db.exists(
				"SP Task", {"reference_name": name, "task_type": sc.TASK_DIFFERENCE, "status": "Open"}
			)
		)

	def test_a_blind_count_never_shows_the_system_quantity_to_the_keeper(self):
		name = self.as_user(self.keeper, sc.start_count, self.main, 1)
		lines = self.as_user(self.keeper, sc.sheet, name)["lines"]
		self.assertTrue(lines)
		self.assertTrue(all("system_qty" not in l and "diff" not in l for l in lines))
		self.assertFalse(any(l.system_qty for l in frappe.get_doc(sc.COUNT, name).lines))
		open_sheet = self.as_user(self.keeper, sc.start_count, self.main, 0)
		self.assertIn("system_qty", self.as_user(self.keeper, sc.sheet, open_sheet)["lines"][0])

	def test_every_line_must_be_counted_and_a_found_item_is_added(self):
		name = self.as_user(self.keeper, sc.start_count, self.main, 1)
		self.as_user(self.keeper, sc.save_counts, name, [{"item_code": MC4, "counted_qty": 50}])
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.keeper, sc.submit_count, name)
		found = make_item("_Test SP94 Found", is_stock_item=1).name
		self.count_all(name, self.keeper)
		sheet = self.as_user(self.keeper, sc.save_counts, name, [{"item_code": found, "counted_qty": 3}])
		self.assertIn(found, [l["item_code"] for l in sheet["lines"]])

	def test_the_difference_is_posted_on_todays_stock(self):
		name = self.as_user(self.keeper, sc.start_count, self.main, 0)
		self.count_all(name, self.keeper, **{PANEL: on_hand(PANEL, self.main) - 1})
		self.as_user(self.keeper, sc.submit_count, name)
		before = on_hand(PANEL, self.main)
		issue(PANEL, self.main, 1)  # it moved after the count
		self.as_user(self.admin, sc.approve_count, name, "خطأ في الصرف")
		self.assertEqual(on_hand(PANEL, self.main), before - 2)

	def test_no_difference_closes_the_count_without_the_admin(self):
		name = self.as_user(self.keeper, sc.start_count, self.main, 1)
		self.count_all(name, self.keeper)
		self.assertEqual(self.as_user(self.keeper, sc.submit_count, name)["status"], sc.APPROVED)
		self.assertFalse(frappe.db.get_value(sc.COUNT, name, "stock_reconciliation"))

	def test_a_rejected_count_is_counted_again(self):
		name = self.as_user(self.keeper, sc.start_count, self.main, 1)
		self.count_all(name, self.keeper, **{MC4: on_hand(MC4, self.main) + 1})
		self.as_user(self.keeper, sc.submit_count, name)
		stock_before = on_hand(MC4, self.main)
		recount = self.as_user(self.admin, sc.reject_count, name, "عد مرة أخرى")["recount"]
		self.assertEqual(on_hand(MC4, self.main), stock_before)
		self.assertEqual(frappe.db.get_value(sc.COUNT, recount, ["recount_of", "status"]), (name, sc.DRAFT))
		self.assertTrue(
			frappe.db.exists(
				"SP Task", {"reference_name": recount, "task_type": sc.TASK_COUNT, "assigned_to": self.keeper}
			)
		)

	def test_only_the_location_counts_and_only_the_admin_decides(self):
		name = self.as_user(self.keeper, sc.start_count, self.main, 1)
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other, sc.sheet, name)
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other, sc.start_count, self.main)
		self.count_all(name, self.keeper, **{MC4: 1})
		self.as_user(self.keeper, sc.submit_count, name)
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.keeper, sc.approve_count, name, "تالف")
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.admin, sc.approve_count, name, " ")

	def test_the_schedule_makes_one_blind_sheet_a_period_and_tasks_the_keeper(self):
		settings = frappe.get_single("Smart Power Settings")
		settings.set("count_schedule", [{"warehouse": self.main, "every": sc.MONTH, "blind": 1}])
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.delete(sc.COUNT, {"warehouse": self.main})
		made = sc.create_scheduled_counts()
		self.assertEqual(len(made), 1)
		self.assertEqual(frappe.db.get_value(sc.COUNT, made[0], ["blind", "scheduled"]), (1, 1))
		self.assertTrue(
			frappe.db.exists(
				"SP Task", {"reference_name": made[0], "task_type": sc.TASK_COUNT, "assigned_to": self.keeper}
			)
		)
		self.assertEqual(sc.create_scheduled_counts(), [])
		due = self.as_user(self.keeper, sc.next_counts)
		self.assertEqual([(d["warehouse"], d["open"]) for d in due], [(self.main, made[0])])

	def test_the_seed_schedules_the_main_store_monthly_and_the_showroom_weekly(self):
		settings = frappe.get_single("Smart Power Settings")
		settings.set("count_schedule", [])
		settings.flags.ignore_permissions = True
		settings.save()
		sc.seed_count_schedule(COMPANY)
		rows = {
			r.warehouse: (r.every, r.blind) for r in frappe.get_single("Smart Power Settings").count_schedule
		}
		self.assertEqual(rows, {self.main: (sc.MONTH, 1), self.showroom: (sc.WEEK, 1)})
