"""Pump curves from Excel, and the head and flow on the pump template (SP-184)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_quotes.calc_templates import CURVE_INPUTS, add_curve_inputs, template_data
from smart_power.sp_stock.pump_curve import covers, curve_of
from smart_power.sp_stock.pump_curve_import import COLUMNS, ERROR, OK, SKIPPED, import_rows
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.test_prices import make_item
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user

load_erpnext_test_data()

HEADER = [ar for _key, ar, _en in COLUMNS]
TEMPLATE = "SP Calc Template"


def flows(code):
	return [(p.flow_m3h, p.head_m) for p in curve_of(code)]


class TestPumpCurveImport(IntegrationTestCase):
	def test_a_good_pump_imports_beside_an_unknown_code(self):
		make_item("SP184-GOOD")
		result = import_rows(
			[HEADER, ["SP184-GOOD", 20, 110], ["SP184-GOOD", 40, 70], ["SP184-NONE", 20, 90]]
		)
		self.assertEqual((result["pumps"], result["points"], result["errors"]), (1, 2, 1))
		self.assertTrue(covers(curve_of("SP184-GOOD"), 90, 30))
		bad = next(r for r in result["rows"] if r["item_code"] == "SP184-NONE")
		self.assertEqual((bad["row"], bad["status"]), (4, ERROR))

	def test_new_points_replace_the_old_curve(self):
		make_item("SP184-REPLACE")
		import_rows([HEADER, ["SP184-REPLACE", 20, 110], ["SP184-REPLACE", 40, 70]])
		import_rows([HEADER, ["SP184-REPLACE", 10, 50]])
		self.assertEqual(flows("SP184-REPLACE"), [(10, 50)])

	def test_a_pump_with_a_bad_row_keeps_its_curve(self):
		make_item("SP184-KEEP")
		import_rows([HEADER, ["SP184-KEEP", 20, 110]])
		result = import_rows([HEADER, ["SP184-KEEP", 30, 90], ["SP184-KEEP", "كثير", 70]])
		self.assertEqual([r["status"] for r in result["rows"]], [SKIPPED, ERROR])
		self.assertEqual(flows("SP184-KEEP"), [(20, 110)])

	def test_a_repeated_flow_and_a_negative_head_are_reported(self):
		make_item("SP184-BAD")
		result = import_rows([HEADER, ["SP184-BAD", 20, 110], ["SP184-BAD", 20, 100], ["SP184-BAD", 30, -1]])
		self.assertEqual([r["status"] for r in result["rows"]], [SKIPPED, ERROR, ERROR])
		self.assertEqual(flows("SP184-BAD"), [])

	def test_a_check_saves_nothing(self):
		make_item("SP184-CHECK")
		result = import_rows([HEADER, ["SP184-CHECK", 20, 110]], dry_run=1)
		self.assertEqual((result["pumps"], result["rows"][0]["status"]), (1, OK))
		self.assertEqual(flows("SP184-CHECK"), [])

	def test_a_file_without_the_columns_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			import_rows([["كود الطلمبة", "الرفع (متر)"], ["SP184-GOOD", 90]])

	def test_only_those_who_edit_items_import(self):
		from smart_power.sp_stock.pump_curve_import import import_curves

		user = make_user("sp.curve.reader@example.com", ("customer_followup",))
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				import_curves("/private/files/none.xlsx")
		finally:
			frappe.set_user("Administrator")


class TestPumpTemplateInputs(IntegrationTestCase):
	def published(self):
		shipped = template_data("pump.json")
		inputs = [r for r in shipped["inputs"] if r["input_key"] not in CURVE_INPUTS]
		doc = make_template(inputs=inputs, lines=shipped["lines"])
		doc.publish()
		return doc

	def test_a_new_version_asks_for_head_and_flow(self):
		old = self.published()
		name = add_curve_inputs(old.template_key)
		new = frappe.get_doc(TEMPLATE, name)
		keys = [r.input_key for r in new.inputs]
		at = keys.index("pump_depth")
		self.assertEqual(keys[at + 1 : at + 3], list(CURVE_INPUTS))
		self.assertEqual([r.idx for r in new.inputs], list(range(1, len(keys) + 1)))
		self.assertTrue(new.is_published)
		self.assertFalse(frappe.db.get_value(TEMPLATE, old.name, "is_published"))
		self.assertFalse(any(r.reqd for r in new.inputs if r.input_key in CURVE_INPUTS))

	def test_it_runs_once(self):
		old = self.published()
		self.assertTrue(add_curve_inputs(old.template_key))
		self.assertIsNone(add_curve_inputs(old.template_key))

	def test_an_existing_quote_keeps_its_version_and_total(self):
		old = self.published()
		quote = make_quotation(save=False)
		quote.sp_calc_template = old.name
		quote.insert()
		total = quote.grand_total
		add_curve_inputs(old.template_key)
		quote.reload()
		self.assertEqual((quote.sp_calc_template, quote.grand_total), (old.name, total))
		self.assertFalse({r.input_key for r in frappe.get_doc(TEMPLATE, old.name).inputs} & set(CURVE_INPUTS))
