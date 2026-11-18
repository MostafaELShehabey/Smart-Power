"""Materials on site (SP-90): what is consumed costs the station, and what goes back does not."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_site.site_log import station_cost
from smart_power.sp_stock import site_materials as sm
from smart_power.sp_stock import transfers as t
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_purchase_orders import COMPANY, ITEM, station
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

RATE = 100
PERPETUAL = {
	"enable_perpetual_inventory": 1,
	"default_inventory_account": "Stock In Hand - _TC",
	"stock_adjustment_account": "Stock Adjustment - _TC",
}


def on_hand(warehouse):
	return flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": warehouse}, "actual_qty"))


class TestSiteMaterials(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_centers(COMPANY)
		seed_accounts(COMPANY)
		frappe.db.set_value("Company", COMPANY, PERPETUAL)
		frappe.clear_cache(doctype="Company")
		frappe.local.enable_perpetual_inventory = {
			**getattr(frappe.local, "enable_perpetual_inventory", {}),
			COMPANY: 1,
		}
		cls.main = wh.warehouse_of(COMPANY, wh.MAIN)
		cls.transit = wh.warehouse_of(COMPANY, wh.TRANSIT)
		if not cls.transit:
			root = frappe.db.get_value(
				"Warehouse", {"company": COMPANY, "is_group": 1, "parent_warehouse": ("is", "not set")}
			)
			cls.transit = (
				frappe.get_doc(
					{
						"doctype": "Warehouse",
						"warehouse_name": "SP90 Transit",
						"company": COMPANY,
						"parent_warehouse": root,
						"warehouse_type": wh.TRANSIT,
					}
				)
				.insert()
				.name
			)
		cls.receiver = make_user("sp.sm.mostafa@example.com", ("site_receiver",))
		cls.other = make_user("sp.sm.other@example.com", ("site_receiver",))
		cls.installer = make_user("sp.sm.installer@example.com", ("installation_manager",))
		cls.keeper = make_user("sp.sm.gaber@example.com", ("main_store_keeper",))
		cls.buyer = make_user("sp.sm.amira@example.com", ("purchase_officer",))

	@classmethod
	def tearDownClass(cls):
		getattr(frappe.local, "enable_perpetual_inventory", {}).pop(COMPANY, None)
		super().tearDownClass()
		frappe.clear_cache(doctype="Company")

	def setUp(self):
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		self.station = station()
		frappe.db.set_value("SP Station", self.station.name, "site_receiver", self.receiver)
		self.station.reload()
		self.site = self.station.site_warehouse or wh.site_warehouse(self.station.project)
		frappe.db.set_value("SP Station", self.station.name, "site_warehouse", self.site)

	def tearDown(self):
		frappe.set_user("Administrator")

	def stock_site(self, qty=20):
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"company": COMPANY,
				"items": [
					{
						"item_code": ITEM,
						"qty": qty,
						"t_warehouse": self.site,
						"basic_rate": RATE,
						"expense_account": "Stock Adjustment - _TC",
					}
				],
			}
		).insert()
		entry.submit()

	def values(self, qty):
		return {
			"station": self.station.name,
			"posting_date": today(),
			"items": [{"item_code": ITEM, "qty": qty}],
		}

	def consume(self, qty):
		frappe.set_user(self.installer)
		entry = sm.record_consumption(self.values(qty))
		frappe.set_user("Administrator")
		return entry

	def send_back(self, qty):
		frappe.set_user(self.receiver)
		entry = sm.return_leftovers(self.values(qty))
		frappe.set_user("Administrator")
		return entry

	def receive(self, entry, qty):
		rows = t._issued_rows(entry)
		frappe.set_user(self.keeper)
		result = sm.receive_return(entry, [{"row": rows[0].name, "qty": qty}])
		frappe.set_user("Administrator")
		return result

	def cost(self):
		return flt(station_cost(self.station.name)["total"])

	def test_only_what_was_consumed_costs_the_station(self):
		self.stock_site(20)
		rate = flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": self.site}, "valuation_rate"))
		self.assertEqual(self.cost(), 0)
		entry = frappe.get_doc("Stock Entry", self.consume(17))
		self.assertEqual(
			(entry.purpose, entry.project, entry.owner),
			("Material Issue", self.station.project, self.installer),
		)
		self.assertEqual(self.cost(), flt(17 * rate, 2))
		self.assertEqual(on_hand(self.site), 3)

	def test_returning_three_leftovers_leaves_the_cost_at_seventeen(self):
		self.stock_site(20)
		self.consume(17)
		cost, main = self.cost(), on_hand(self.main)
		name = self.send_back(3)
		self.assertEqual(on_hand(self.site), 0)
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{
					"reference_name": name,
					"task_type": sm.TASK_RETURN,
					"assigned_to": self.keeper,
					"status": "Open",
				},
			)
		)
		self.assertEqual(self.receive(name, 3)["status"], sm.RETURNED)
		self.assertEqual((on_hand(self.site), on_hand(self.main)), (0, main + 3))
		self.assertEqual(self.cost(), cost)
		self.assertFalse(
			frappe.db.exists(
				"SP Task", {"reference_name": name, "task_type": sm.TASK_RETURN, "status": "Open"}
			)
		)

	def test_a_short_return_stays_in_transit_and_is_flagged(self):
		self.stock_site(5)
		name = self.send_back(5)
		transit = on_hand(self.transit)
		result = self.receive(name, 4)
		self.assertEqual((result["status"], result["short"]), (sm.DISCREPANCY, 1))
		self.assertEqual(on_hand(self.transit), transit - 4)
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{
					"reference_name": name,
					"task_type": sm.TASK_DIFFERENCE,
					"assigned_to": self.buyer,
					"status": "Open",
				},
			)
		)
		self.assertEqual(self.receive(name, 1)["status"], sm.RETURNED)

	def test_nothing_beyond_what_the_site_holds_can_leave_it(self):
		self.stock_site(2)
		self.assertRaises(frappe.ValidationError, self.consume, 3)
		self.assertRaises(frappe.ValidationError, self.send_back, 3)

	def test_a_site_request_becomes_a_transfer_order(self):
		frappe.set_user(self.receiver)
		request = sm.request_materials({**self.values(4), "note": "ناقص مواسير"})
		frappe.set_user("Administrator")
		task = {
			"reference_name": request,
			"task_type": sm.TASK_REQUEST,
			"assigned_to": self.buyer,
			"status": "Open",
		}
		self.assertTrue(frappe.db.exists("SP Task", task))
		frappe.set_user(self.buyer)
		self.assertIn(request, [r.name for r in sm.open_requests()])
		transfer = sm.make_transfer(request, wh.MAIN, t.OTHER)
		frappe.set_user("Administrator")
		doc = frappe.get_doc(t.ORDER, transfer)
		self.assertEqual(
			(doc.sp_station, flt(doc.items[0].qty), doc.sp_transfer_status), (self.station.name, 4, t.CREATED)
		)
		self.assertEqual(frappe.db.get_value(t.ORDER, request, "sp_request_status"), sm.CONVERTED)
		self.assertFalse(frappe.db.exists("SP Task", task))
		frappe.set_user(self.buyer)
		self.assertRaises(frappe.ValidationError, sm.make_transfer, request, wh.MAIN, t.OTHER)

	def test_who_may_do_what(self):
		self.stock_site(5)
		frappe.set_user(self.receiver)
		self.assertRaises(frappe.PermissionError, sm.record_consumption, self.values(1))
		frappe.set_user(self.other)
		self.assertRaises(frappe.PermissionError, sm.return_leftovers, self.values(1))
		self.assertRaises(frappe.PermissionError, sm.request_materials, self.values(1))
		name = self.send_back(1)
		frappe.set_user(self.other)
		self.assertRaises(frappe.PermissionError, sm.receive_return, name, [])

	def test_a_received_transfer_used_up_on_site_is_consumed(self):
		order = self.finished_transfer(2)
		self.consume(2)
		self.assertEqual(frappe.db.get_value(t.ORDER, order, "sp_transfer_status"), sm.CONSUMED)

	def test_a_received_transfer_sent_back_is_leftovers_returned(self):
		order = self.finished_transfer(2)
		self.consume(1)
		self.assertEqual(frappe.db.get_value(t.ORDER, order, "sp_transfer_status"), t.RECEIVED)
		self.receive(self.send_back(1), 1)
		self.assertEqual(frappe.db.get_value(t.ORDER, order, "sp_transfer_status"), sm.LEFTOVERS)

	def finished_transfer(self, qty):
		self.stock_site(qty)
		order = frappe.get_doc(
			{
				"doctype": t.ORDER,
				"material_request_type": "Material Transfer",
				"company": COMPANY,
				"schedule_date": today(),
				"sp_station": self.station.name,
				"sp_transfer_status": t.RECEIVED,
				"items": [{"item_code": ITEM, "qty": qty, "schedule_date": today(), "warehouse": self.site}],
			}
		).insert()
		return order.name

	def test_the_return_note_prints_without_a_price(self):
		self.stock_site(3)
		name = self.send_back(3)
		note = sm.return_print(frappe.get_doc("Stock Entry", name))
		self.assertEqual((note.station, note.source, note.target), (self.station.name, self.site, self.main))
		self.assertNotIn("rate", note.lines[0])
		self.assertIn(name, frappe.get_print("Stock Entry", name, print_format="SP Return Note"))
