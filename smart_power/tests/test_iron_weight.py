"""Chassis iron by scale weight (SP-178): the scale weight is final, landed cost raises the cost
per kg the calculator reads, and the variance report compares the two weights."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_quotes import chassis_calc as cc
from smart_power.sp_quotes.engine import valuation_rate
from smart_power.sp_stock import goods_receipt as gr
from smart_power.sp_stock import iron_weight as iw
from smart_power.sp_stock import receipt_confirmation as rc
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock.purchase_orders import MAIN_STORE, RECEIVED, enable_batches
from smart_power.tests.test_goods_receipt import SIGNATURE, photo
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_purchase_orders import COMPANY, SUPPLIER, order, row
from smart_power.tests.test_receipt_confirmation import PERPETUAL
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

THEORETICAL, SCALE = 3858, 3820  # the story's example
DEMO_RATE = 60  # a demo price per kg, not a real one
LANDED = 7640  # transport, unloading and labour: 2 per kg on 3,820 kg
AGRI = "أجري سولار"


class TestIronWeight(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_centers(COMPANY)
		enable_batches()
		cc.seed_factories()
		frappe.db.set_value("Company", COMPANY, PERPETUAL)
		cls.forget_perpetual_setting()
		cls.confirmer = make_user("sp.iron.aya@example.com", ("receipt_confirmer",))
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
		set_setting(iron_weight_variance_pct=2)

	def iron(self, code):
		return make_item(code, stock_uom="Kg", is_stock_item=1, sp_is_weighed=1).name

	def iron_order(self, item, kg=THEORETICAL):
		po = order(
			[row(item_code=item, qty=kg, rate=DEMO_RATE)],
			sp_destination_type=MAIN_STORE,
			sp_theoretical_weight_kg=kg,
		).insert()
		po.submit()
		return po

	def weigh(self, po, kg):
		lines = [{"purchase_order_item": po.items[0].name, "received_qty": kg, "condition": "OK"}]
		name = gr.record_receipt(po.name, self.main, lines, photo(), SIGNATURE)["name"]
		frappe.set_user(self.confirmer)
		rc.confirm_receipt(name)
		frappe.set_user("Administrator")
		return name

	def stock(self, item):
		return flt(frappe.db.get_value("Bin", {"warehouse": self.main, "item_code": item}, "actual_qty"))

	def report_row_of(self, receipt):
		po = frappe.db.get_value("Purchase Receipt Item", {"parent": receipt}, "purchase_order")
		return self.report_row(po)

	def report_row(self, po):
		return next(r for r in iw.variance() if r["purchase_order"] == po)

	def test_3858_theoretical_and_3820_on_the_scale(self):
		item = self.iron("SP-IRON-KG-A")
		po = self.iron_order(item)
		self.weigh(po, SCALE)
		self.assertEqual(self.stock(item), SCALE)  # stock rises by the scale weight
		po.reload()
		self.assertEqual((po.items[0].qty, po.sp_status), (SCALE, RECEIVED))  # nothing stays open
		r = self.report_row(po.name)
		self.assertEqual((r["theoretical_kg"], r["actual_kg"], r["variance_kg"]), (THEORETICAL, SCALE, -38))
		self.assertEqual(r["warning"], "")  # -0.98%, under the 2% warning

	def test_the_confirmer_sees_the_scale_weight_against_the_theoretical_before_confirming(self):
		item = self.iron("SP-IRON-KG-E")
		po = self.iron_order(item, kg=1000)
		expected = next(c for c in gr.expected_deliveries() if c["purchase_order"] == po.name)
		self.assertTrue(expected["lines"][0]["weighed"])  # the receiver is told to type the scale weight
		lines = [{"purchase_order_item": po.items[0].name, "received_qty": 1030, "condition": "OK"}]
		name = gr.record_receipt(po.name, self.main, lines, photo(), SIGNATURE)["name"]
		frappe.set_user(self.confirmer)
		pending = next(r for r in rc.pending_receipts() if r["name"] == name)
		self.assertTrue(pending["lines"][0]["weighed"])
		weight = pending["weight"]
		self.assertEqual(
			(weight["theoretical_kg"], weight["actual_kg"], weight["variance_pct"]), (1000, 1030, 3)
		)
		self.assertTrue(weight["warning"])  # 3% is above the 2% limit
		frappe.set_user("Administrator")
		self.assertEqual(iw.weight_check(po.name, 1010)["warning"], "")  # 1% passes quietly

	def test_a_heavier_supply_is_received_and_warned_above_the_threshold(self):
		item = self.iron("SP-IRON-KG-B")
		po = self.iron_order(item, kg=1000)
		self.weigh(po, 1030)  # more than ordered: the scale weight is final
		self.assertEqual(self.stock(item), 1030)
		r = self.report_row(po.name)
		self.assertEqual((r["variance_kg"], r["variance_pct"]), (30, 3))
		self.assertTrue(r["warning"])

	def test_landed_cost_raises_the_cost_per_kg_the_next_calc_reads(self):
		item = self.iron("SP-IRON-KG-C")
		receipt = self.weigh(self.iron_order(item), SCALE)
		before = valuation_rate(item)
		lcv = frappe.get_doc(
			{
				"doctype": "Landed Cost Voucher",
				"company": COMPANY,
				"distribute_charges_based_on": "Qty",
				"purchase_receipts": [
					{
						"receipt_document_type": "Purchase Receipt",
						"receipt_document": receipt,
						"supplier": SUPPLIER,
					}
				],
				"taxes": [
					{
						"description": "نقل وتنزيل وعمالة",
						"expense_account": "Expenses Included In Valuation - _TC",
						"amount": LANDED,
					}
				],
			}
		)
		lcv.get_items_from_purchase_receipts()
		lcv.insert()
		lcv.submit()
		self.assertAlmostEqual(valuation_rate(item) - before, LANDED / SCALE)  # +2 per kg
		factory = frappe.get_doc(cc.FACTORY, AGRI)
		factory.iron_item = item
		factory.save()
		self.assertAlmostEqual(cc.factory_dict(AGRI)["iron_cost_kg"], valuation_rate(item))
		self.assertEqual(self.report_row_of(receipt)["factory"], AGRI)  # grouped by its iron item
		calc = frappe.get_doc(
			{"doctype": cc.CALC, "factory": AGRI, "panel_width_m": 1.303, "arrays": [{"panels": 30}]}
		).insert()
		self.assertAlmostEqual(calc.iron_cost_kg, before + LANDED / SCALE)  # the next calc uses it

	def test_a_po_takes_its_theoretical_weight_from_its_chassis_calc(self):
		calc = frappe.get_doc(
			{"doctype": cc.CALC, "factory": AGRI, "panel_width_m": 1.303, "arrays": [{"panels": 30}]}
		).insert()
		po = order(
			[row(item_code=self.iron("SP-IRON-KG-D"), qty=300, rate=DEMO_RATE)], sp_chassis_calc=calc.name
		)
		po.sp_destination_type = MAIN_STORE
		po.insert()
		self.assertAlmostEqual(po.sp_theoretical_weight_kg, calc.iron_weight_kg)
