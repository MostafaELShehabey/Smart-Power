"""A quote calculated from its template (SP-55): lines, manual qty, item change, locked markup."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_quotes.quote_calc import calculate_quote, set_line_override
from smart_power.tests.test_calc_engine import golden, set_up_golden
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_test_case, make_user

load_erpnext_test_data()


class TestQuoteCalc(IntegrationTestCase):
	def setUp(self):
		self.data = golden()
		set_up_golden(self.data)
		self.template = make_template(**self.data["template"])
		self.template.publish()
		case = frappe.get_doc("SP Case", make_test_case())
		case.append("system_types", {"system_type": "System Type-PUMP"})
		case.save()
		self.quote = make_quotation(case=case.name)

	def rows(self):
		doc = frappe.get_doc("Quotation", self.quote.name)
		return doc, {row.sp_line_key or row.item_code: row for row in doc.items}

	def test_calculate_writes_the_lines_and_keeps_hand_rows(self):
		result = calculate_quote(self.quote.name, self.data["inputs"])
		doc, rows = self.rows()
		self.assertEqual(doc.sp_calc_template, self.template.name)  # the published one for PUMP
		self.assertEqual(frappe.parse_json(doc.sp_design_inputs)["depth"], 99)
		self.assertEqual(
			set(rows), {"motor", "pipes", "cable", "rope", "panels", "installation", "winch", "_Test Item"}
		)
		self.assertEqual((rows["pipes"].qty, rows["pipes"].rate, rows["pipes"].sp_cost), (33, 360, 300))
		self.assertEqual((rows["motor"].item_code, rows["motor"].sp_lock_markup), ("SPT-MOTOR-A50", 1))
		self.assertEqual(rows["panels"].rate, 2690)
		# SP-56: a line with no item but its own text reaches the quote on its kind's service item
		self.assertEqual(
			(
				rows["installation"].item_code,
				rows["installation"].item_name,
				rows["installation"].sp_line_kind,
			),
			("SP-MANUAL", "تركيب وبرمجة", "Manual"),
		)
		self.assertEqual((rows["winch"].item_code, rows["winch"].sp_line_kind), ("SP-WINCH", "Winch"))
		self.assertEqual((rows["installation"].rate, rows["installation"].sp_cost), (8000, 5000))
		skipped = {r["line_key"] for r in result.rule_results if r["level"] == "info"}
		self.assertEqual(skipped, set())
		# the optional line goes under the total, not into it (SP-59)
		self.assertEqual(
			[(r.line_key, r.item_code, r.amount) for r in doc.sp_optional_lines],
			[("stainless_motor", "SPT-STAINLESS", 69000)],
		)

	def test_manual_qty_is_kept_on_recalculation(self):
		calculate_quote(self.quote.name, self.data["inputs"])
		set_line_override(self.quote.name, "pipes", "qty", 38)
		calculate_quote(self.quote.name)
		_, rows = self.rows()
		self.assertEqual((rows["pipes"].qty, rows["pipes"].sp_is_manual_qty), (38, 1))
		set_line_override(self.quote.name, "pipes", "qty", None)  # back to the formula
		self.assertEqual(self.rows()[1]["pipes"].qty, 33)

	def test_item_can_be_changed(self):
		calculate_quote(self.quote.name, self.data["inputs"])
		set_line_override(self.quote.name, "motor", "item_code", "SPT-MOTOR-B40")
		self.assertEqual(self.rows()[1]["motor"].rate, 41000)

	def test_locked_line_refuses_a_markup_change(self):
		calculate_quote(self.quote.name, self.data["inputs"])
		with self.assertRaises(frappe.ValidationError):
			set_line_override(self.quote.name, "pipes", "markup", 5, reason="أقل")

	def test_markup_change_needs_a_reason_and_is_logged(self):
		calculate_quote(self.quote.name, self.data["inputs"])
		with self.assertRaises(frappe.ValidationError):
			set_line_override(self.quote.name, "rope", "markup", 50)
		set_line_override(self.quote.name, "rope", "markup", 50, reason="عميل قديم")
		self.assertEqual(self.rows()[1]["rope"].rate, 15)
		log = frappe.get_all(
			"SP Edit Reason Log",
			{"reference_name": self.quote.name},
			["old_value", "new_value", "reason"],
		)
		self.assertEqual(
			[(r.old_value, r.new_value, r.reason) for r in log], [("rope: 20", "rope: 50", "عميل قديم")]
		)

	def test_a_template_used_by_a_quote_is_frozen(self):
		draft = frappe.get_doc("SP Calc Template", self.template.new_version())
		other = make_quotation(case=self.quote.sp_case)
		frappe.db.set_value("Quotation", other.name, "sp_calc_template", draft.name)
		draft.reload()
		draft.lines[0].qty_formula = "2"
		with self.assertRaises(frappe.ValidationError):
			draft.save()

	def test_only_a_draft_version(self):
		calculate_quote(self.quote.name, self.data["inputs"])
		doc = frappe.get_doc("Quotation", self.quote.name)
		doc.submit()
		with self.assertRaises(frappe.ValidationError):
			calculate_quote(self.quote.name)

	def test_only_cost_roles(self):
		user = make_user("sp.calc.followup@example.com", ("customer_followup",), extra_roles=("Sales User",))
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				calculate_quote(self.quote.name, self.data["inputs"])
		finally:
			frappe.set_user("Administrator")

	def test_dialog_learns_the_default_template_and_its_inputs(self):
		from smart_power.sp_quotes.quote_calc import template_for_quote

		info = template_for_quote(self.quote.name)
		self.assertEqual(info["template"], self.template.name)  # the published one for PUMP
		self.assertEqual(
			[i.input_key for i in info["inputs"]], [i["input_key"] for i in self.data["template"]["inputs"]]
		)

	def test_a_hand_row_may_repeat_a_template_item(self):
		# found in the browser sweep: ERPNext refused the same item on two quote lines
		from smart_power.sp_sales.setup import allow_repeated_items

		allow_repeated_items()
		doc = frappe.get_doc("Quotation", self.quote.name)
		doc.items[0].item_code = "SPT-PIPE"
		doc.save()
		calculate_quote(self.quote.name, self.data["inputs"])
		pipes = [row for row in self.rows()[0].items if row.item_code == "SPT-PIPE"]
		self.assertEqual(len(pipes), 2)  # the template's pipes line and the hand row

	def test_a_fractional_service_line_goes_as_one_lump(self):
		# SP-56: 65.625 kW of chassis on the Manual item (Nos, a whole unit): one lump, same money
		template = make_template(
			inputs=[{"input_key": "kw", "label": "kW", "default_value": "65.625"}],
			lines=[
				{
					"line_key": "chassis",
					"description": "شاسيهات (لكل كيلو وات)",
					"qty_formula": "kw",
					"cost_source": "Per-kW default",
					"cost_default": 1300,
					"default_markup": 12,
					"rounding": "Nearest 10",
				},
				{
					"line_key": "installation",
					"description": "تركيب وبرمجة",
					"qty_formula": "round(kw)",
					"cost_source": "Manual",
					"cost_default": 200,
					"default_markup": 25,
					"rounding": "Nearest 5",
				},
			],
		)
		template.publish()
		calculate_quote(self.quote.name, {}, template.name)
		_, rows = self.rows()
		chassis = rows["chassis"]
		self.assertEqual(
			(chassis.item_code, chassis.qty, chassis.rate), ("SP-MANUAL", 1, 95812.5)
		)  # 65.625 x 1460
		self.assertEqual((chassis.sp_cost, chassis.item_name), (85312.5, "شاسيهات (لكل كيلو وات) x 65.625"))
		installation = rows["installation"]  # a whole quantity stays as it is
		self.assertEqual(
			(installation.qty, installation.rate, installation.item_name), (66, 250, "تركيب وبرمجة")
		)
