"""Calculation templates (SP-55): keys, safe formulas, versions and publishing."""

import frappe
from frappe.tests import IntegrationTestCase

PUMP = "System Type-PUMP"


def sample_inputs():
	return [
		{"input_key": "hp", "label": "HP", "input_type": "Float", "reqd": 1},
		{"input_key": "depth", "label": "Depth (m)", "input_type": "Float", "reqd": 1},
		{
			"input_key": "pipe_type",
			"label": "Pipe Type",
			"input_type": "Select",
			"options": "Plastic\nSteel",
			"default_value": "Plastic",
		},
		{"input_key": "plastic_pipe_m", "label": "Plastic Pipe (m)", "default_value": "3"},
		{"input_key": "steel_pipe_m", "label": "Steel Pipe (m)", "default_value": "6"},
		{"input_key": "cable_allowance", "label": "Cable Allowance (m)", "default_value": "10"},
		{"input_key": "rope_allowance", "label": "Rope Allowance (m)", "default_value": "30"},
	]


def sample_lines():
	return [
		{
			"line_key": "pipes",
			"qty_formula": "ceil(depth / (plastic_pipe_m if pipe_type == 'Plastic' else steel_pipe_m))",
		},
		{"line_key": "cable", "qty_formula": "depth + cable_allowance"},
		{"line_key": "rope", "qty_formula": "depth * 2 + rope_allowance"},
	]


def make_template(key=None, inputs=None, lines=None, **kw):
	# tests in a class share a transaction: each template gets its own code
	key = key or "T" + frappe.generate_hash(length=8).upper()
	return frappe.get_doc(
		{
			"doctype": "SP Calc Template",
			"template_key": key,
			"template_name": "قالب طلمبات تجريبي",
			"offer_type": PUMP,
			"inputs": sample_inputs() if inputs is None else inputs,
			"lines": sample_lines() if lines is None else lines,
			**kw,
		}
	).insert()


class TestCalcTemplate(IntegrationTestCase):
	def test_versions_are_named_by_code(self):
		first = make_template(key="TVERSIONS")
		self.assertEqual((first.name, first.version), ("TVERSIONS-v1", 1))
		second = frappe.get_doc("SP Calc Template", first.new_version())
		self.assertEqual((second.version, second.previous_version), (2, first.name))
		self.assertEqual(len(second.lines), len(first.lines))
		self.assertFalse(second.is_published)

	def test_unknown_name_names_the_line(self):
		lines = [*sample_lines(), {"line_key": "fittings", "qty_formula": "pipes.qty + elbows"}]
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_template(lines=lines)
		self.assertIn("fittings", str(ctx.exception))
		self.assertIn("elbows", str(ctx.exception))

	def test_cost_formula_is_checked(self):
		# SP-56: a formula cost needs its formula, and its names are checked like a quantity's
		line = {"line_key": "fittings", "cost_source": "Formula"}
		with self.assertRaises(frappe.ValidationError):
			make_template(lines=[*sample_lines(), line])
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_template(lines=[*sample_lines(), {**line, "cost_formula": "pipes.amount / elbows"}])
		self.assertIn("elbows", str(ctx.exception))
		make_template(lines=[*sample_lines(), {**line, "cost_formula": "pipes.amount / 4"}])

	def test_a_line_sees_only_the_lines_above_it(self):
		lines = [
			{"line_key": "rope", "qty_formula": "cable.qty * 2"},
			{"line_key": "cable", "qty_formula": "depth"},
		]
		with self.assertRaises(frappe.ValidationError):
			make_template(lines=lines)
		make_template(
			lines=[
				{"line_key": "cable", "qty_formula": "depth"},
				{"line_key": "rope", "qty_formula": "cable.qty * 2"},
			]
		)

	def test_formulas_that_are_not_expressions_are_refused(self):
		for formula in ("depth +", "(lambda: 1)()", "depth.__class__"):
			with self.assertRaises(frappe.ValidationError, msg=formula):
				make_template(lines=[{"line_key": "x", "qty_formula": formula}])

	def test_keys(self):
		for key in ("Depth", "2pipes", "ceil", "item", "with space"):
			with self.assertRaises(frappe.ValidationError, msg=key):
				make_template(inputs=[{"input_key": key, "label": "x"}], lines=[])
		with self.assertRaises(frappe.ValidationError):
			make_template(lines=[{"line_key": "depth", "qty_formula": "1"}])  # same as an input

	def test_select_default_must_be_an_option(self):
		inputs = [
			{
				"input_key": "pipe_type",
				"label": "x",
				"input_type": "Select",
				"options": "Plastic",
				"default_value": "Steel",
			}
		]
		with self.assertRaises(frappe.ValidationError):
			make_template(inputs=inputs, lines=[])

	def test_brand_priority_needs_its_fields(self):
		with self.assertRaises(frappe.ValidationError):
			make_template(
				lines=[
					{"line_key": "motor", "selection_rule": "Brand priority", "item_group": "All Item Groups"}
				]
			)
		make_template(
			lines=[
				{
					"line_key": "motor",
					"selection_rule": "Brand priority",
					"item_group": "All Item Groups",
					"capacity_field": "hp",
					"need_formula": "hp",
				}
			]
		)

	def test_locked_btc_lines_are_locked(self):
		doc = make_template(
			lines=[{"line_key": "motor", "qty_formula": "1", "pricing_method": "Locked BTC price"}]
		)
		self.assertTrue(doc.lines[0].lock_markup)

	def test_published_version_is_frozen(self):
		doc = make_template()
		doc.publish()
		doc.reload()
		doc.lines[0].qty_formula = "depth / 6"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.description = "ملاحظة"
		doc.save()  # notes may change

	def test_one_published_version_per_offer_type(self):
		first = make_template()
		first.publish()
		second = frappe.get_doc("SP Calc Template", first.new_version())
		second.publish()
		self.assertFalse(frappe.db.get_value("SP Calc Template", first.name, "is_published"))
		from smart_power.sp_quotes.doctype.sp_calc_template.sp_calc_template import published_template

		self.assertEqual(published_template(PUMP), second.name)

	def test_publish_needs_lines(self):
		with self.assertRaises(frappe.ValidationError):
			make_template(lines=[]).publish()


class TestCalcTemplateSample(IntegrationTestCase):
	def test_run_sample_prices_the_form_as_it_is(self):
		doc = make_template(
			lines=[
				{
					"line_key": "rope",
					"qty_formula": "depth * 2 + rope_allowance",
					"cost_source": "Manual",
					"cost_default": 10,
					"pricing_method": "Pass-through",
				}
			]
		)
		result = doc.run_sample({"hp": 40, "depth": 99})
		self.assertEqual(result.lines[0].qty, 228)
		self.assertEqual(result.totals.sell, 2280)


class TestCalcTemplateNewVersion(IntegrationTestCase):
	def test_new_version_of_a_published_template_is_an_editable_draft(self):
		# found while building SP-134: copy_doc kept "published" on the copy, so it was frozen
		published = make_template()
		published.publish()
		draft = frappe.get_doc(
			"SP Calc Template", frappe.get_doc("SP Calc Template", published.name).new_version()
		)
		self.assertFalse(draft.is_published)
		self.assertTrue(frappe.db.get_value("SP Calc Template", published.name, "is_published"))
		draft.lines[0].qty_formula = "depth / 6"
		draft.save()  # not frozen


class TestExcelRounding(IntegrationTestCase):
	def test_halves_go_up_as_in_the_sheets(self):
		# SP-56: Mohamed's sheet rounds 112.5 kW of installation to 113, not 112
		from smart_power.sp_quotes import formulas

		self.assertEqual(formulas.excel_round(112.5), 113)
		self.assertEqual(formulas.excel_round(2006.5), 2007)
		self.assertEqual(formulas.excel_round(8.393, 2), 8.39)
		self.assertEqual(formulas.excel_round(20075, -1), 20080)
		self.assertEqual(formulas.excel_round(-2.5), -3)  # away from zero
		self.assertEqual(formulas.mround(20065, 10), 20070)
		self.assertEqual(formulas.mround(68.75, 5), 70)
		self.assertEqual(formulas.evaluate("round(depth / 2)", {"depth": 5}, "Line x"), 3)
