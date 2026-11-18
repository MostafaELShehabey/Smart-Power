"""Default item selection (SP-168): the brand order, the next size up, panels from stock first,
the pump by its curve, a chosen brand, and quotes that keep the order they started with."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services.settings import brand_order
from smart_power.sp_quotes.calc_templates import PICK_RULES, add_pick_rules, template_data
from smart_power.sp_quotes.engine import calculate
from smart_power.sp_quotes.quote_calc import brands_of, keep_brand_order
from smart_power.sp_sales.quotation import new_version
from smart_power.sp_stock.item import seed_item_groups
from smart_power.sp_stock.on_hand import on_hand
from smart_power.sp_stock.warehouses import _spec
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.test_consignment import SUPPLIER as CONSIGNMENT_OWNER
from smart_power.tests.test_consignment import ensure_supplier
from smart_power.tests.test_prices import make_item
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, set_setting

load_erpnext_test_data()

GROUP = "_Test Item Group"
WAREHOUSE = "_Test Warehouse - _TC"
COMPANY = "_Test Company"
TEMPLATE = "SP Calc Template"
SANCH, INVT = "SP168 SANCH", "SP168 INVT"


def make_brands():
	for brand in (SANCH, INVT):
		if not frappe.db.exists("Brand", brand):
			frappe.get_doc({"doctype": "Brand", "brand": brand}).insert()


def order(*brands):
	set_setting(
		brand_priorities=[
			{"item_group": GROUP, "brand": b, "priority": i} for i, b in enumerate(brands, start=1)
		]
	)


def template(rule="Brand priority", field="hp", inputs=()):
	return make_template(
		inputs=[{"input_key": "need", "label": "Need", "input_type": "Float"}, *inputs],
		lines=[
			{
				"line_key": "pick",
				"selection_rule": rule,
				"item_group": GROUP,
				"capacity_field": field,
				"need_formula": "need",
				"qty_formula": "1",
				"cost_source": "Per-kW default",
				"pricing_method": "Pass-through",
			}
		],
	)


DUTY = (
	{"input_key": "required_head_m", "label": "Head", "input_type": "Float"},
	{"input_key": "required_flow_m3h", "label": "Flow", "input_type": "Float"},
)


def picked(doc, overrides=None, brands=None, **inputs):
	result = calculate(doc.name, {"need": 100, **inputs}, overrides, brands=brands)
	return result.lines[0].item_code, result.rule_results


def stock(item, qty=5, warehouse=WAREHOUSE):
	frappe.get_doc({"doctype": "Bin", "item_code": item, "warehouse": warehouse, "actual_qty": qty}).insert()


class TestItemSelection(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_item_groups()
		make_brands()
		ensure_supplier()

	def setUp(self):
		# tests in a class share a transaction: each one has its own items
		self.key = frappe.generate_hash(length=6).upper()
		frappe.db.set_value("Item", {"item_group": GROUP, "sp_hp": (">", 0)}, "disabled", 1)
		self.small = self.item(SANCH, 90)
		self.invt = self.item(INVT, 125)
		self.invt_big = self.item(INVT, 150)
		order(SANCH, INVT)

	def item(self, brand, hp):
		code = f"SP168-{self.key}-{brand[-4:]}-{hp}"
		make_item(code, item_group=GROUP, brand=brand, sp_hp=hp)
		return code

	def test_the_next_size_up_of_the_next_brand(self):
		# 110 HP: SANCH stops at 90, so the INVT model of the next size up
		self.assertEqual(picked(template(), need=110)[0], self.invt)

	def test_the_first_brand_wins_when_it_covers_the_need(self):
		sanch = self.item(SANCH, 200)
		self.assertEqual(picked(template(), need=110)[0], sanch)

	def test_a_chosen_brand_gets_its_smallest_model(self):
		sanch = self.item(SANCH, 200)
		doc = template()
		self.assertEqual(picked(doc, {"pick": {"brand": INVT}}, need=110)[0], self.invt)
		self.assertEqual(picked(doc, need=110)[0], sanch)

	def test_a_chosen_brand_without_a_model_says_so(self):
		item, notes = picked(template(), {"pick": {"brand": SANCH}}, need=110)
		self.assertIsNone(item)
		self.assertTrue([n for n in notes if n["level"] == "warn" and SANCH in n["message"]])

	def test_a_line_without_a_sized_rule_takes_no_brand(self):
		doc = template(rule="First in stock")
		with self.assertRaises(frappe.ValidationError):
			picked(doc, {"pick": {"brand": INVT}})

	def test_company_stock_comes_first(self):
		stock(self.invt_big)
		self.assertEqual(picked(template("Stock first"), need=110)[0], self.invt_big)

	def test_consignment_comes_after_company_stock(self):
		box = frappe.get_doc(
			{
				"doctype": "SP Consignment Container",
				"supplier": CONSIGNMENT_OWNER,
				"item": self.invt_big,
				"company": COMPANY,
				"container_no": self.key,
				"pallets": 1,
				"per_pallet": 10,
			}
		).insert()
		self.assertEqual(on_hand([self.invt_big])[self.invt_big]["consignment"], box.available_qty)
		doc = template("Stock first")
		self.assertEqual(picked(doc, need=110)[0], self.invt_big)
		stock(self.invt)
		self.assertEqual(picked(doc, need=110)[0], self.invt)

	def test_without_stock_the_priority_decides(self):
		self.assertEqual(picked(template("Stock first"), need=110)[0], self.invt)

	def test_goods_on_a_site_are_not_stock_on_hand(self):
		name = _spec()["sites"]
		group = frappe.db.get_value("Warehouse", {"warehouse_name": name, "company": COMPANY, "is_group": 1})
		if not group:
			group = (
				frappe.get_doc(
					{"doctype": "Warehouse", "warehouse_name": name, "company": COMPANY, "is_group": 1}
				)
				.insert()
				.name
			)
		site = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": f"SP168 {self.key}",
				"company": COMPANY,
				"parent_warehouse": group,
			}
		).insert()
		stock(self.invt_big, warehouse=site.name)
		self.assertEqual(on_hand([self.invt_big])[self.invt_big]["company"], 0)
		self.assertEqual(picked(template("Stock first"), need=110)[0], self.invt)

	def curve(self, code, points):
		item = frappe.get_doc("Item", code)
		item.set("sp_curve_points", [{"flow_m3h": f, "head_m": h} for f, h in points])
		item.save()

	def test_the_pump_is_the_first_whose_curve_covers_the_duty(self):
		self.curve(self.invt, [(20, 60), (40, 40)])
		self.curve(self.invt_big, [(20, 110), (40, 70)])
		doc = template("Pump curve", inputs=DUTY)
		duty = {"required_head_m": 90, "required_flow_m3h": 30}
		self.assertEqual(picked(doc, need=110, **duty)[0], self.invt_big)

	def test_no_curve_covers_the_duty(self):
		self.curve(self.invt, [(20, 60), (40, 40)])
		doc = template("Pump curve", inputs=DUTY)
		item, notes = picked(doc, need=110, required_head_m=500, required_flow_m3h=30)
		self.assertIsNone(item)
		self.assertTrue([n for n in notes if n["level"] == "warn"])

	def test_without_curves_the_size_decides_and_the_line_says_so(self):
		doc = template("Pump curve", inputs=DUTY)
		item, notes = picked(doc, need=110, required_head_m=90, required_flow_m3h=30)
		self.assertEqual(item, self.invt)
		self.assertTrue([n for n in notes if n["level"] == "info"])

	def test_without_a_duty_the_size_decides(self):
		self.curve(self.invt_big, [(20, 110), (40, 70)])
		self.assertEqual(picked(template("Pump curve", inputs=DUTY), need=110)[0], self.invt)


class TestBrandOrderKept(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_brands()

	def test_a_reorder_changes_new_quotes_only(self):
		order(SANCH, INVT)
		quote = frappe._dict(sp_case="CS-TEST")
		keep_brand_order(quote)
		order(INVT, SANCH)
		self.assertEqual(brands_of(quote)[GROUP], [SANCH, INVT])
		self.assertEqual(brand_order()[GROUP], [INVT, SANCH])

	def test_a_quote_and_its_new_version_keep_the_order(self):
		order(SANCH, INVT)
		quote = make_quotation()
		self.assertEqual(brands_of(quote)[GROUP], [SANCH, INVT])
		order(INVT, SANCH)
		quote.submit()
		copy = frappe.get_doc("Quotation", new_version(quote.name))
		self.assertEqual(brands_of(copy)[GROUP], [SANCH, INVT])
		self.assertEqual(brands_of(make_quotation())[GROUP], [INVT, SANCH])


class TestPumpTemplateRules(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_item_groups()

	def published(self, keep=None):
		shipped = template_data("pump.json")
		lines = [
			{**row, "selection_rule": keep if keep and row["line_key"] == "pump" else "Brand priority"}
			if row["line_key"] in PICK_RULES
			else row
			for row in shipped["lines"]
		]
		doc = make_template(inputs=shipped["inputs"], lines=lines)
		doc.publish()
		return doc

	def rules(self, name):
		lines = frappe.get_doc(TEMPLATE, name).lines
		return {r.line_key: r.selection_rule for r in lines if r.line_key in PICK_RULES}

	def test_a_new_version_carries_the_rules_once(self):
		old = self.published()
		name = add_pick_rules(old.template_key)
		self.assertEqual(self.rules(name), PICK_RULES)
		self.assertEqual(set(self.rules(old.name).values()), {"Brand priority"})
		self.assertIsNone(add_pick_rules(old.template_key))

	def test_a_rule_the_admin_changed_stays(self):
		old = self.published(keep="First in stock")
		name = add_pick_rules(old.template_key)
		self.assertEqual(self.rules(name), {"panels": "Stock first", "pump": "First in stock"})
