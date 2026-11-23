"""The chassis calculator in quotes (SP-167): a chassis-only quote is its calc, and a station
quote's chassis line takes its kW and cost from the calc."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_quotes import chassis_calc as cc
from smart_power.sp_quotes import chassis_quote as cq
from smart_power.sp_quotes.quote_calc import calculate_quote
from smart_power.sp_quotes.quote_print import quote_print
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_test_case, set_setting

load_erpnext_test_data()

AGRI = "أجري سولار"
WIDTH, WATT = 1.303, 715  # 30 Tongwei 715 panels: 21.45 kW
DEMO_IRON_COST, DEMO_PART_COST = 100, 5  # demo costs, not the factory's real ones
PER_KW, LINE_MARKUP = 1300, 12


def quote_for(system_type):
	case = frappe.get_doc("SP Case", make_test_case())
	case.append("system_types", {"system_type": system_type})
	case.save()
	return make_quotation(case=case.name)


class TestChassisQuote(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cc.seed_factories()
		factory = frappe.get_doc(cc.FACTORY, AGRI)
		factory.iron_cost_kg = DEMO_IRON_COST
		for part in factory.parts:
			if part.basis == "Unit cost":
				part.unit_cost = DEMO_PART_COST
		factory.save()

	def setUp(self):
		set_setting(chassis_station_markup=cq.LOCKED)

	def calc(self, quotation):
		return frappe.get_doc(
			{
				"doctype": cc.CALC,
				"factory": AGRI,
				"quotation": quotation,
				"panel_width_m": WIDTH,
				"panel_watt": WATT,
				"arrays": [{"panels": 30}],
			}
		).insert()

	def station_quote(self):
		template = make_template(
			inputs=[{"input_key": "kw", "label": "kW", "default_value": "21.45"}],
			lines=[
				{
					"line_key": "chassis",
					"description": "شاسيهات (لكل كيلو وات)",
					"qty_formula": "kw",
					"cost_source": "Per-kW default",
					"cost_default": PER_KW,
					"default_markup": LINE_MARKUP,
					"rounding": "Nearest 10",
				}
			],
		)
		template.publish()
		quote = quote_for("System Type-PUMP")
		calculate_quote(quote.name, {}, template.name)
		return quote

	def chassis_row(self, quote):
		doc = frappe.get_doc("Quotation", quote.name)
		return next(r for r in doc.items if r.sp_line_key == cq.CHASSIS_LINE)

	def test_a_chassis_only_quote_prints_the_analysis_and_its_total(self):
		quote = quote_for(cq.CHASSIS_ONLY)
		calc = self.calc(quote.name)
		doc = frappe.get_doc("Quotation", quote.name)
		doc.set("items", [r for r in doc.items if r.sp_line_key == cq.CHASSIS_LINE])  # no hand row
		doc.save()
		row = self.chassis_row(quote)
		self.assertEqual((row.qty, row.rate, row.sp_cost), (1, calc.total_sale, calc.total_cost))
		printed = quote_print(doc)
		self.assertEqual(printed.totals.total, calc.total_sale)  # the PDF total is the analysis total
		chassis_lines = printed.lines
		self.assertEqual([line["no"] for line in chassis_lines], list(range(1, len(calc.lines) + 1)))
		self.assertEqual([line["description"] for line in chassis_lines], [r.part for r in calc.lines])
		self.assertEqual(
			sum(line["amount"] for line in chassis_lines), sum(r.sale_amount for r in calc.lines)
		)

	def test_the_calc_replaces_the_empty_line_a_new_chassis_quote_starts_with(self):
		from smart_power.sp_quotes.special_lines import MANUAL, service_item

		quote = quote_for(cq.CHASSIS_ONLY)
		label = frappe.db.get_value("SP List Value", cq.CHASSIS_ONLY, "value_ar")
		doc = frappe.get_doc("Quotation", quote.name)
		# as builder.new_quote leaves it: one manual line named after the system type, no price
		doc.set("items", [{"item_code": service_item(MANUAL), "item_name": label, "qty": 1, "rate": 0}])
		doc.append("items", {"item_code": service_item(MANUAL), "item_name": "نقل", "qty": 1, "rate": 500})
		doc.save()
		calc = self.calc(quote.name)
		doc.reload()
		# the empty line is gone, the hand line with its own price stays, the calc's row is added
		hand = doc.items[0]
		self.assertEqual((hand.item_name, hand.sp_line_key, flt(hand.rate)), ("نقل", None, 500))
		self.assertEqual([r.sp_line_key for r in doc.items], [None, cq.CHASSIS_LINE])
		self.assertEqual(doc.items[1].rate, calc.total_sale)

	def test_without_a_calc_the_station_line_keeps_the_per_kw_default(self):
		row = self.chassis_row(self.station_quote())
		self.assertEqual(row.sp_cost, flt(21.45 * PER_KW))

	def test_a_pump_quote_with_a_calc_takes_the_chassis_kw_and_cost_from_it(self):
		quote = self.station_quote()
		calc = self.calc(quote.name)  # saving the calc updates the draft quote
		row = self.chassis_row(quote)
		self.assertIn("21.45", row.item_name)  # the calc's kW (a lump of its amount)
		self.assertAlmostEqual(row.sp_cost, calc.total_cost)
		self.assertAlmostEqual(row.rate, calc.total_sale)  # the factory's locked markups
		self.assertEqual(row.sp_lock_markup, 1)

	def test_the_line_markup_setting_prices_the_calc_cost_with_the_lines_markup(self):
		set_setting(chassis_station_markup=cq.LINE_MARKUP)
		quote = self.station_quote()
		calc = self.calc(quote.name)
		per_kw = flt(calc.total_cost) / 21.45
		expected = round(per_kw * (1 + LINE_MARKUP / 100) / 10) * 10 * 21.45
		self.assertAlmostEqual(self.chassis_row(quote).rate, expected, places=2)
