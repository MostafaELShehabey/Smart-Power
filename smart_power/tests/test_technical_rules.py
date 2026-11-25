"""Technical rules on quotes (SP-169): the inverter covers the motor, the depth divides by the pipe."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.rules import RuleBlocked, evaluate
from smart_power.rules.sales import QUOTE_SEND_EVENT
from smart_power.rules.technical import DEPTH_RULE, INVERTER_RULE, LEFT_OFF_RULE, nearest_depths, rated_kw
from smart_power.sp_core.documents import seed_quote_template
from smart_power.sp_quotes import builder
from smart_power.sp_quotes.engine import calculate
from smart_power.sp_quotes.quote_send import send_options, send_quote
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_quote_send import blank_pdf
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_rule, set_setting

load_erpnext_test_data()

GROUP = "_Test Item Group"
PLASTIC = "بلاستيك"
STEEL = "حديد"


def hits(doc):
	return {h.spec.key: h for h in evaluate(doc, QUOTE_SEND_EVENT)}


class TestInverterRule(IntegrationTestCase):
	def setUp(self):
		set_rule(INVERTER_RULE, "Warn")
		set_rule(DEPTH_RULE, "Warn")
		key = frappe.generate_hash(length=6).upper()
		self.motor = make_item(f"SP169-MTR-{key}", item_group=GROUP, sp_hp=110).name
		self.small = make_item(f"SP169-INV45-{key}", item_group=GROUP, sp_kw=45).name
		self.large = make_item(f"SP169-INV90-{key}", item_group=GROUP, sp_kw=90).name

	def quote(self, inverter):
		quote = make_quotation(save=False)
		row = quote.items[0]
		rate, qty = row.rate, row.qty
		quote.set(
			"items",
			[
				{"item_code": self.motor, "qty": qty, "rate": rate, "sp_line_key": "motor"},
				{"item_code": inverter, "qty": qty, "rate": rate, "sp_line_key": "inverter"},
			],
		)
		return quote.insert()

	def send(self, quote, **kw):
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		seed_quote_template()
		set_setting(default_quote_print_format="SP Quotation")
		with patch("frappe.get_print", return_value=blank_pdf()):
			return send_quote(quote.name, **kw)

	def test_a_110_hp_motor_needs_more_than_a_45_kw_inverter(self):
		hit = hits(self.quote(self.small))[INVERTER_RULE]
		self.assertEqual(hit.level, "Warn")
		self.assertIn("(45 kW)", hit.finding.message)
		self.assertIn("(82.06 kW)", hit.finding.message)

	def test_a_large_enough_inverter_passes(self):
		self.assertNotIn(INVERTER_RULE, hits(self.quote(self.large)))

	def test_power_converts_between_hp_and_kw(self):
		self.assertAlmostEqual(rated_kw(self.motor), 82.06)
		self.assertEqual(rated_kw(self.small), 45)

	def test_off_says_nothing(self):
		set_rule(INVERTER_RULE, "Off")
		self.assertNotIn(INVERTER_RULE, hits(self.quote(self.small)))

	def test_warn_sends_and_is_listed_for_the_admin(self):
		quote = self.quote(self.small)
		result = self.send(quote)
		self.assertTrue([w for w in result["warnings"] if self.small in w])
		self.assertTrue(frappe.db.exists("SP Review Item", {"reference_name": quote.name}))

	def test_block_stops_the_send(self):
		set_rule(INVERTER_RULE, "Block")
		quote = self.quote(self.small)
		user = make_user("sp.tr.creator@example.com", ("quote_creator",))
		frappe.db.set_value("SP Case", quote.sp_case, "quote_creator", user, update_modified=False)
		frappe.set_user(user)
		try:
			self.assertEqual(len(send_options(quote.name)["technical"]["block"]), 1)
			self.assertFalse(send_options(quote.name)["technical"]["can_override"])
			with self.assertRaises(RuleBlocked):
				self.send(quote, reason="لازم يتبعت")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Quotation", quote.name, "docstatus"), 0)

	def test_the_admin_passes_a_block_only_with_a_reason(self):
		set_rule(INVERTER_RULE, "Block")
		quote = self.quote(self.small)
		with self.assertRaises(RuleBlocked):
			self.send(quote)
		self.send(quote, reason="العميل عنده إنفرتر قائم")
		self.assertEqual(frappe.db.get_value("Quotation", quote.name, "docstatus"), 1)
		self.assertTrue(
			frappe.db.exists(
				"SP Rule Override Log", {"rule_key": INVERTER_RULE, "reference_name": quote.name}
			)
		)


class TestDepthRule(IntegrationTestCase):
	def setUp(self):
		set_rule(DEPTH_RULE, "Warn")
		self.pipe = make_item(f"SP169-PIPE-{frappe.generate_hash(length=6).upper()}", item_group=GROUP).name
		self.template = make_template(
			inputs=[
				{"input_key": "pump_depth", "label": "Depth", "input_type": "Float", "reqd": 1},
				{
					"input_key": "pipe_type",
					"label": "Pipe",
					"input_type": "Select",
					"options": f"{PLASTIC}\n{STEEL}",
					"default_value": PLASTIC,
				},
				{
					"input_key": "plastic_pipe_m",
					"label": "Plastic",
					"input_type": "Float",
					"default_value": "3",
				},
				{"input_key": "steel_pipe_m", "label": "Steel", "input_type": "Float", "default_value": "6"},
			],
			lines=[
				{
					"line_key": "column_pipes",
					"item_code": self.pipe,
					"qty_formula": f"ceil(pump_depth / (plastic_pipe_m if pipe_type == '{PLASTIC}' else steel_pipe_m))",
					"cost_source": "Per-kW default",
					"pricing_method": "Pass-through",
				}
			],
		)

	def quote(self, **inputs):
		quote = make_quotation(save=False)
		quote.sp_calc_template = self.template.name
		quote.sp_design_inputs = json.dumps(inputs, ensure_ascii=False)
		return quote.insert()

	def test_the_nearest_valid_depths(self):
		self.assertEqual(nearest_depths(100, 3), [99, 102])
		self.assertEqual(nearest_depths(99, 3), [])
		self.assertEqual(nearest_depths(2, 3), [3])
		self.assertEqual(nearest_depths(100, 0), [])

	def test_depth_100_with_3_m_plastic_pipes_suggests_99_or_102(self):
		hit = hits(self.quote(pump_depth=100))[DEPTH_RULE]
		self.assertEqual(hit.finding.data, {"input": "pump_depth", "depths": [99, 102]})

	def test_the_chosen_pipe_type_decides_the_length(self):
		self.assertNotIn(DEPTH_RULE, hits(self.quote(pump_depth=102, pipe_type=STEEL)))
		self.assertEqual(
			hits(self.quote(pump_depth=100, pipe_type=STEEL))[DEPTH_RULE].finding.data["depths"], [96, 102]
		)

	def test_applying_a_suggestion_clears_the_rule_and_sets_the_pipes(self):
		quote = self.quote(pump_depth=100)
		page = builder.load(quote.name)
		rule = next(r for r in page["rules"] if r["key"] == DEPTH_RULE)
		self.assertEqual((rule["input"], rule["depths"]), ("pump_depth", [99, 102]))
		fixed = builder.recalc(quote.name, {"inputs": {"pump_depth": rule["depths"][0]}})
		self.assertNotIn(DEPTH_RULE, [r["key"] for r in fixed["rules"]])
		pipes = calculate(self.template.name, {"pump_depth": 99}).lines[0]
		self.assertEqual(pipes.qty, 33)


class TestLinesLeftOff(IntegrationTestCase):
	"""BUG-23: a line waiting for its item, or with no price, went out missing from the quote."""

	def setUp(self):
		set_rule(LEFT_OFF_RULE, "Block")
		self.pipe = make_item(f"SP23-PIPE-{frappe.generate_hash(length=6).upper()}", item_group=GROUP).name
		self.board = make_item(f"SP23-BRD-{frappe.generate_hash(length=6).upper()}", item_group=GROUP).name
		self.template = make_template(
			inputs=[],
			lines=[
				{
					"line_key": "pipes",
					"item_code": self.pipe,
					"qty_formula": "2",
					"cost_source": "Per-kW default",
					"cost_default": 50,
					"pricing_method": "Pass-through",
				},
				# waiting for the creator to pick the board from its group
				{
					"line_key": "board",
					"item_group": GROUP,
					"description": "لوحة تجربة",
					"qty_formula": "1",
					"cost_source": "Per-kW default",
					"cost_default": 900,
					"pricing_method": "Pass-through",
				},
				# a service line whose price the template does not give yet
				{
					"line_key": "install",
					"description": "تركيب تجربة",
					"qty_formula": "1",
					"cost_source": "Per-kW default",
					"cost_default": 0,
					"pricing_method": "Pass-through",
				},
			],
		)

	def quote(self, overrides=None):
		quote = make_quotation(save=False)
		quote.sp_calc_template = self.template.name
		quote.sp_design_inputs = "{}"
		quote.sp_calc_overrides = json.dumps(overrides or {})
		return quote.insert()

	def send(self, quote, **kw):
		return TestInverterRule.send(self, quote, **kw)

	def test_it_blocks_by_default(self):
		from smart_power.rules import registry

		self.assertEqual(registry()[LEFT_OFF_RULE].default_level, "Block")

	def test_a_line_waiting_for_its_item_or_its_price_is_named(self):
		hit = hits(self.quote())[LEFT_OFF_RULE]
		self.assertEqual(hit.level, "Block")
		self.assertEqual(len(hit.finding.data["lines"]), 2)
		self.assertNotIn("pipes", hit.finding.data["lines"])

	def test_the_send_stops_until_the_lines_are_filled(self):
		quote = self.quote()
		user = make_user("sp.lo.creator@example.com", ("quote_creator",))
		frappe.db.set_value("SP Case", quote.sp_case, "quote_creator", user, update_modified=False)
		frappe.set_user(user)
		try:
			with self.assertRaises(RuleBlocked):
				self.send(quote)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Quotation", quote.name, "docstatus"), 0)
		filled = self.quote({"board": {"item_code": self.board}, "install": {"cost": 300}})
		self.assertNotIn(LEFT_OFF_RULE, hits(filled))

	def test_the_admin_sends_it_with_a_reason(self):
		quote = self.quote()
		with self.assertRaises(RuleBlocked):
			self.send(quote)
		self.send(quote, reason="البنود ستضاف في نسخة لاحقة")
		self.assertEqual(frappe.db.get_value("Quotation", quote.name, "docstatus"), 1)
