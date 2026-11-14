"""The calculation engine (SP-55), checked against a golden file."""

import json
import os

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.sp_quotes.engine import calculate
from smart_power.sp_stock import prices
from smart_power.sp_stock.prices import BTC, COST
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.test_prices import make_category, make_item
from smart_power.tests.utils import load_erpnext_test_data, set_setting

load_erpnext_test_data()

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "calc_pump_sample.json")
WAREHOUSE = "_Test Warehouse - _TC"


def golden() -> dict:
	with open(GOLDEN, encoding="utf-8") as f:
		return json.load(f)


def set_up_golden(data: dict):
	"""The golden file's item group, brands, items, prices and brand priority."""
	group = data["item_group"]
	if not frappe.db.exists("Item Group", group):
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": group, "parent_item_group": "All Item Groups"}
		).insert()
	for brand in data["brands"]:
		if not frappe.db.exists("Brand", brand):
			frappe.get_doc({"doctype": "Brand", "brand": brand}).insert()
	for spec in data["items"]:
		extra = {"item_group": group} if spec.get("group") else {}
		if spec.get("brand"):
			extra["brand"] = spec["brand"]
		if spec.get("hp"):
			extra["sp_hp"] = spec["hp"]
		make_item(spec["code"], **extra)
		if "cost" in spec:
			prices.set_price(spec["code"], COST, spec["cost"], reason="golden file")
		if "btc" in spec:
			prices.set_price(spec["code"], BTC, spec["btc"], reason="golden file")
	set_setting(
		brand_priorities=[
			{"item_group": group, "brand": brand, "priority": priority}
			for brand, priority in data["brands"].items()
		]
	)


class TestCalcEngine(IntegrationTestCase):
	def setUp(self):
		self.data = golden()
		set_up_golden(self.data)
		self.template = make_template(**self.data["template"])

	def calc(self, inputs=None, overrides=None):
		return calculate(self.template.name, inputs or self.data["inputs"], overrides)

	def test_golden_pump(self):
		result = self.calc()
		lines = {line.line_key: line for line in result.lines}
		for key, expected in self.data["expected"]["lines"].items():
			for field, value in expected.items():
				if isinstance(value, str):
					self.assertEqual(lines[key][field], value, f"{key}.{field}")
				else:
					self.assertAlmostEqual(lines[key][field], value, places=2, msg=f"{key}.{field}")
		for field, value in self.data["expected"]["totals"].items():
			self.assertAlmostEqual(result.totals[field], value, places=2, msg=field)
		self.assertEqual(result.rule_results, [])
		self.assertEqual((result.template, result.version), (self.template.name, 1))

	def test_the_story_example(self):
		lines = {line.line_key: line for line in self.calc().lines}
		depth, cable_allowance = 99, 10  # the template's cable allowance default
		self.assertEqual(lines["pipes"].qty, 33)
		self.assertEqual(lines["cable"].qty, depth + cable_allowance)
		self.assertEqual(lines["rope"].qty, depth * 2 + 30)

	def test_steel_pipe_input(self):
		lines = {
			line.line_key: line for line in self.calc({**self.data["inputs"], "pipe_type": "Steel"}).lines
		}
		self.assertEqual(lines["pipes"].qty, 17)  # ceil(99 / 6)

	def test_locked_line_refuses_a_markup_change(self):
		with self.assertRaises(frappe.ValidationError):
			self.calc(overrides={"pipes": {"markup": 5}})
		with self.assertRaises(frappe.ValidationError):
			self.calc(overrides={"motor": {"markup": 5}})
		rope = next(
			line for line in self.calc(overrides={"rope": {"markup": 50}}).lines if line.line_key == "rope"
		)
		self.assertAlmostEqual(rope.rate, 15)

	def test_manual_qty_is_kept_and_flagged(self):
		lines = {line.line_key: line for line in self.calc(overrides={"pipes": {"qty": 38}}).lines}
		self.assertEqual((lines["pipes"].qty, lines["pipes"].is_manual_qty), (38, 1))
		self.assertEqual(lines["cable"].is_manual_qty, 0)

	def test_item_can_be_changed(self):
		motor = self.calc(overrides={"motor": {"item_code": "SPT-MOTOR-B40"}}).lines[0]
		self.assertEqual((motor.item_code, motor.rate), ("SPT-MOTOR-B40", 41000))

	def test_unknown_override_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.calc(overrides={"pipes": {"amount": 1}})

	def test_required_input(self):
		with self.assertRaises(frappe.MandatoryError):
			self.calc({"hp": 40})

	def test_no_item_covers_the_need(self):
		result = self.calc({**self.data["inputs"], "hp": 75})
		self.assertIsNone(result.lines[0].item_code)
		self.assertEqual([r["line_key"] for r in result.rule_results if r["level"] == "warn"][:1], ["motor"])

	def test_missing_price_warns(self):
		template = make_template(
			inputs=[],
			lines=[
				{
					"line_key": "rope",
					"item_code": "SPT-ROPE",
					"qty_formula": "1",
					"pricing_method": "Locked BTC price",
				}
			],
		)
		result = calculate(template.name)
		self.assertEqual(result.lines[0].rate, 0)
		self.assertEqual(result.rule_results[0]["line_key"], "rope")

	def test_stale_price_warns(self):
		category = make_category("SPT Calc Stale", max_age_days=30).name
		frappe.db.set_value("Item", "SPT-PIPE", "sp_price_age_category", category)
		prices.set_price("SPT-PIPE", BTC, 365, price_date=add_days(today(), -40), reason="old")
		stale = [r for r in self.calc().rule_results if r.get("stale")]
		self.assertEqual([r["line_key"] for r in stale], ["pipes"])

	def test_first_in_stock_and_valuation_rate(self):
		frappe.get_doc(
			{
				"doctype": "Bin",
				"item_code": "SPT-MOTOR-B40",
				"warehouse": WAREHOUSE,
				"actual_qty": 2,
				"stock_value": 70400,
			}
		).insert()
		template = make_template(
			inputs=[],
			lines=[
				{
					"line_key": "motor",
					"selection_rule": "First in stock",
					"item_group": self.data["item_group"],
					"qty_formula": "1",
					"cost_source": "Valuation rate",
					"pricing_method": "Pass-through",
				}
			],
		)
		motor = calculate(template.name).lines[0]
		self.assertEqual((motor.item_code, motor.cost, motor.rate), ("SPT-MOTOR-B40", 35200, 35200))

	def test_formulas_read_the_picked_item_and_earlier_lines(self):
		template = make_template(
			inputs=[{"input_key": "hp", "label": "HP", "default_value": "40"}],
			lines=[
				{
					"line_key": "motor",
					"selection_rule": "Brand priority",
					"item_group": self.data["item_group"],
					"capacity_field": "hp",
					"need_formula": "hp",
					"qty_formula": "1",
					"pricing_method": "Locked BTC price",
				},
				{
					"line_key": "spare",
					"item_code": "SPT-ROPE",
					"qty_formula": "motor.item.hp - hp + motor.qty",
				},
			],
		)
		self.assertEqual(calculate(template.name).lines[1].qty, 11)  # 50 - 40 + 1
