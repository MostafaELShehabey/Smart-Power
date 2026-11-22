"""Shared purchases (SP-83): one order split between stations by amount; confirming the receipt
issues the goods out of the store and charges each station its share."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_stations.costing import actual_cost
from smart_power.sp_stock import goods_receipt as gr
from smart_power.sp_stock import receipt_confirmation as rc
from smart_power.sp_stock import shared_purchase as sp
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock.purchase_orders import MAIN_STORE, SITE_DELIVERY, enable_batches
from smart_power.tests.test_goods_receipt import SIGNATURE, photo
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_purchase_orders import COMPANY, order, row, station
from smart_power.tests.test_receipt_confirmation import PERPETUAL
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

RATE, QTY = 100, 300  # a 30,000 cable drum, in metres
SHARES = (12000, 18000)


class TestSharedPurchase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_centers(COMPANY)
		seed_accounts(COMPANY)
		enable_batches()
		frappe.db.set_value("Company", COMPANY, PERPETUAL)
		cls.forget_perpetual_setting()
		cls.confirmer = make_user("sp.spl.aya@example.com", ("receipt_confirmer",))
		cls.cable = make_item("SP-SPL-CABLE", is_stock_item=1).name
		cls.stations = [station(), station()]
		cls.main = wh.warehouse_of(COMPANY, wh.MAIN)

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		cls.forget_perpetual_setting()

	@staticmethod
	def forget_perpetual_setting():
		frappe.clear_document_cache("Company", COMPANY)
		getattr(frappe.local, "enable_perpetual_inventory", {}).pop(COMPANY, None)

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_setting(account_map=[])
		sp.seed_account_map(COMPANY)

	def shared_order(self, shares=SHARES, **kw):
		splits = [{"station": st.name, "amount": a} for st, a in zip(self.stations, shares, strict=True)]
		kw.setdefault("sp_destination_type", MAIN_STORE)
		return order([row(item_code=self.cable, qty=QTY, rate=RATE)], sp_station_splits=splits, **kw)

	def receive(self, po, qty=QTY):
		lines = [{"purchase_order_item": po.items[0].name, "received_qty": qty, "condition": "OK"}]
		name = gr.record_receipt(po.name, self.main, lines, photo(), SIGNATURE)["name"]
		frappe.set_user(self.confirmer)
		result = rc.confirm_receipt(name)
		frappe.set_user("Administrator")
		return name, result["purchase_invoice"]

	def costs(self):
		return [flt(actual_cost(st.name)["direct"]) for st in self.stations]

	def in_store(self):
		return flt(
			frappe.db.get_value("Bin", {"warehouse": self.main, "item_code": self.cable}, "actual_qty")
		)

	def shared_balance(self):
		account = frappe.db.get_value("Account", {"company": COMPANY, "account_name": sp.SHARED_ACCOUNT})
		return flt(
			frappe.db.sql(
				"select sum(debit - credit) from `tabGL Entry` where account=%s and is_cancelled=0", account
			)[0][0]
		)

	def test_a_30000_order_split_12000_18000_raises_each_stations_cost_by_its_share(self):
		po = self.shared_order().insert()
		po.submit()
		before, stock, shared = self.costs(), self.in_store(), self.shared_balance()
		receipt, _invoice = self.receive(po)
		after = self.costs()
		self.assertEqual([a - b for a, b in zip(after, before, strict=True)], list(SHARES))
		self.assertEqual(self.in_store(), stock)  # the drum left the store at confirmation
		self.assertAlmostEqual(self.shared_balance(), shared)  # the clearing account nets 0
		issue = frappe.db.get_value(gr.RECEIPT, receipt, sp.ISSUE_FIELD)
		self.assertEqual(frappe.db.get_value("Stock Entry", issue, "docstatus"), 1)

	def test_splits_summing_to_29000_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.shared_order(shares=(12000, 17000)).insert()
		self.shared_order(shares=(12000, 17999.5)).insert()  # to the pound

	def test_a_shared_order_names_its_stations_only_in_the_split(self):
		with self.assertRaises(frappe.ValidationError):  # not one station's site
			self.shared_order(sp_station=self.stations[0].name, sp_destination_type=SITE_DELIVERY).insert()
		po = self.shared_order()
		po.sp_station_splits[1].station = po.sp_station_splits[0].station
		with self.assertRaises(frappe.ValidationError):  # a station once
			po.insert()

	def test_a_partial_receipt_shares_what_arrived_and_cancelling_takes_it_back(self):
		po = self.shared_order().insert()
		po.submit()
		before, stock = self.costs(), self.in_store()
		receipt, invoice = self.receive(po, qty=100)  # 10,000 of the 30,000
		self.assertEqual([a - b for a, b in zip(self.costs(), before, strict=True)], [4000, 6000])
		frappe.get_doc("Purchase Invoice", invoice).cancel()
		frappe.get_doc(gr.RECEIPT, receipt).cancel()
		self.assertEqual(self.costs(), before)
		self.assertEqual(self.in_store(), stock)
		issue = frappe.db.get_value(gr.RECEIPT, receipt, sp.ISSUE_FIELD)
		self.assertEqual(frappe.db.get_value("Stock Entry", issue, "docstatus"), 2)

	def test_the_shares_add_up_to_the_value_to_the_piastre(self):
		splits = [frappe._dict(amount=a) for a in (1, 1, 1)]
		self.assertEqual(sum(sp.shares(100, splits)), 100)
		self.assertEqual(sp.shares(100, splits), [33.33, 33.33, 33.34])
