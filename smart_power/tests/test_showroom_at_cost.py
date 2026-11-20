"""Showroom stock to a station at cost, and the showroom's refill from the main store (SP-89)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import SHOWROOM, center, seed_centers
from smart_power.sp_site.site_log import issue_materials, station_cost
from smart_power.sp_stock import transfers as t
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_purchase_orders import COMPANY, station
from smart_power.tests.test_site_materials import PERPETUAL
from smart_power.tests.test_transfers import on_hand
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

INVERTER = "_Test SP89 Inverter"
COST, BTC = 18000, 21000


def receive(item, warehouse, qty, rate):
	entry = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"purpose": "Material Receipt",
			"company": COMPANY,
			"items": [{"item_code": item, "qty": qty, "t_warehouse": warehouse, "basic_rate": rate}],
		}
	).insert()
	entry.submit()


def showroom_income() -> float:
	"""What the showroom center has earned: income accounts on the Showroom center."""
	rows = frappe.db.sql(
		"""select sum(gle.credit - gle.debit) from `tabGL Entry` gle
		join `tabAccount` acc on acc.name = gle.account
		where gle.cost_center = %s and gle.is_cancelled = 0 and acc.root_type = 'Income'""",
		center(SHOWROOM, COMPANY),
	)
	return flt(rows[0][0])


class TestShowroomAtCost(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		seed_centers(COMPANY)
		# stock postings reach the books only with perpetual inventory on (as SP-90's tests)
		frappe.db.set_value("Company", COMPANY, PERPETUAL)
		frappe.clear_cache(doctype="Company")
		frappe.local.enable_perpetual_inventory = {
			**getattr(frappe.local, "enable_perpetual_inventory", {}),
			COMPANY: 1,
		}
		cls.main = wh.warehouse_of(COMPANY, wh.MAIN)
		cls.showroom = wh.warehouse_of(COMPANY, wh.SHOWROOM)
		if not wh.warehouse_of(COMPANY, wh.TRANSIT):
			root = frappe.db.get_value(
				"Warehouse", {"company": COMPANY, "is_group": 1, "parent_warehouse": ("is", "not set")}
			)
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": "SP89 Transit",
					"company": COMPANY,
					"parent_warehouse": root,
					"warehouse_type": wh.TRANSIT,
				}
			).insert()
		cls.buyer = make_user("sp.sc.amira@example.com", ("purchase_officer",))
		cls.keeper = make_user("sp.sc.gaber@example.com", ("main_store_keeper",))
		cls.showroom_keeper = make_user("sp.sc.hussein@example.com", ("showroom_store_keeper",))
		cls.receiver = make_user("sp.sc.mostafa@example.com", ("site_receiver",))
		cls.other = make_user("sp.sc.other@example.com", ("site_receiver",))
		make_item(INVERTER, is_stock_item=1)
		if frappe.db.exists("Price List", "BTC"):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": INVERTER, "price_list": "BTC", "price_list_rate": BTC}
			).insert()
		receive(INVERTER, cls.showroom, 1, COST)
		receive(INVERTER, cls.main, 5, COST)

	@classmethod
	def tearDownClass(cls):
		getattr(frappe.local, "enable_perpetual_inventory", {}).pop(COMPANY, None)
		super().tearDownClass()
		frappe.clear_cache(doctype="Company")

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def arrive(self, name, user):
		rows = t._issued_rows(frappe.db.get_value(t.ORDER, name, "sp_issue_entry"))
		return self.as_user(
			user, t.confirm_transfer, name, [{"row": rows[0].name, "qty": rows[0].transfer_qty}]
		)

	def test_an_inverter_from_the_showroom_costs_the_station_18000_and_earns_the_showroom_nothing(self):
		site_station = station()
		frappe.db.set_value("SP Station", site_station.name, "site_receiver", self.receiver)
		income = showroom_income()
		cost = station_cost(site_station.name)["total"]
		name = self.as_user(
			self.buyer,
			t.create_transfer,
			{
				"station": site_station.name,
				"source_kind": wh.SHOWROOM,
				"transport": t.OTHER,
				"planned_date": today(),
				"items": [{"item_code": INVERTER, "qty": 1}],
			},
		)
		self.as_user(self.showroom_keeper, t.issue_transfer, name)
		self.arrive(name, self.receiver)
		site = wh.site_warehouse(site_station.project)
		self.assertEqual(on_hand(INVERTER, site), 1)
		issue_materials(
			COMPANY, site, site_station.project, [{"item_code": INVERTER, "qty": 1}], today(), "SP89"
		)
		self.assertEqual(station_cost(site_station.name)["total"] - cost, COST)  # the cost, not the BTC price
		self.assertEqual(showroom_income() - income, 0)

	def test_the_showroom_asks_the_main_store_for_a_refill(self):
		showroom, main = on_hand(INVERTER, self.showroom), on_hand(INVERTER, self.main)
		name = self.as_user(
			self.showroom_keeper,
			t.request_refill,
			{"items": [{"item_code": INVERTER, "qty": 2}], "company": COMPANY},
		)
		order = frappe.get_doc(t.ORDER, name)
		self.assertEqual(
			(order.set_from_warehouse, order.set_warehouse, order.sp_station, order.sp_transfer_status),
			(self.main, self.showroom, None, t.CREATED),
		)
		self.assertTrue(
			frappe.db.exists(
				"SP Task", {"reference_name": name, "task_type": t.TASK_ISSUE, "assigned_to": self.keeper}
			)
		)
		seen = [r["name"] for r in self.as_user(self.showroom_keeper, t.my_transfers)["transfers"]]
		self.assertIn(name, seen)
		self.as_user(self.keeper, t.issue_transfer, name)
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{"reference_name": name, "task_type": t.TASK_RECEIVE, "assigned_to": self.showroom_keeper},
			)
		)
		self.assertEqual(self.arrive(name, self.showroom_keeper)["status"], t.RECEIVED)
		self.assertEqual(
			(on_hand(INVERTER, self.showroom), on_hand(INVERTER, self.main)), (showroom + 2, main - 2)
		)

	def test_only_the_showroom_asks_for_a_refill(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(
				self.receiver,
				t.request_refill,
				{"items": [{"item_code": INVERTER, "qty": 1}], "company": COMPANY},
			)
