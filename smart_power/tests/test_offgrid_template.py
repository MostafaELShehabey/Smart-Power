"""The off-grid calculation template (SP-172), checked against the owner's off-grid file (16-9-2026).

The file's load table gives 3,170 W of load, 25,560 Wh by day and 13,990 Wh by night, so 7,190.9 W
of panels, a 4.755 kW inverter and 404.8 Ah of batteries at 48 V. The products round up (owner's
decision 22-11-2026): two complete strings of seven 625 W panels, the smallest inverter at or
above 4.755 kW and three 200 Ah batteries. The prices here are demo numbers, not the file's.
"""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_quotes import offgrid
from smart_power.sp_quotes.builder import request_inputs
from smart_power.sp_quotes.calc_templates import template_data
from smart_power.sp_quotes.engine import calculate
from smart_power.sp_quotes.quote_calc import write_lines
from smart_power.sp_stock import prices
from smart_power.sp_stock.item import seed_item_groups
from smart_power.sp_stock.prices import BTC, COST
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.test_prices import make_item
from smart_power.tests.utils import load_erpnext_test_data, set_setting

load_erpnext_test_data()

BRAND = "SP172 Brand"
PANELS, INVERTERS, BATTERIES = "ألواح شمسية", "إنفرترات ودرايفات", "بطاريات"
# the file's load table: device, qty, watts, day hours, night hours
GOLDEN_LOADS = (
	("مكيف 1.5 حصان (انفرتر)", 2, 1125, 8, 3),
	("مروحة سقف", 4, 80, 8, 7),
	("نظام كاميرات", 1, 140, 12, 12),
	("ثلاجة حديثة", 2, 80, 12, 12),
	("شاشة + راوتر + شواحن", 1, 100, 10, 4),
	("لمبة ليد 40 وات", 5, 40, 2, 5),
)
DEMO_PRICE = 100  # a demo price for every item, not a real one


def load_rows():
	return [
		{"device": d, "qty": q, "watts": w, "day_hours": day, "night_hours": night}
		for d, q, w, day, night in GOLDEN_LOADS
	]


class TestOffgridTemplate(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_item_groups()
		if not frappe.db.exists("Brand", BRAND):
			frappe.get_doc({"doctype": "Brand", "brand": BRAND}).insert()
		cls.items = {
			"panel": make_item("SP172-PANEL-625", item_group=PANELS, brand=BRAND, sp_watt=625),
			"inv5": make_item("SP172-INV-5KW", item_group=INVERTERS, brand=BRAND, sp_kw=5),
			"inv8": make_item("SP172-INV-8KW", item_group=INVERTERS, brand=BRAND, sp_kw=8),
			"bat": make_item("SP172-BAT-200AH", item_group=BATTERIES, brand=BRAND, sp_battery_ah=200),
		}
		for item in cls.items.values():
			for key in (COST, BTC):
				prices.set_price(item.name, key, DEMO_PRICE, reason="SP-172 test")
		for key in ("inv5", "inv8", "bat"):  # a 48 V bank's inverters and batteries (BUG-25)
			frappe.db.set_value("Item", cls.items[key].name, "sp_system_voltage", 48)
		shipped = template_data("offgrid.json")
		cls.template = make_template(inputs=shipped["inputs"], lines=shipped["lines"])

	def setUp(self):
		groups = (PANELS, INVERTERS, BATTERIES)
		set_setting(brand_priorities=[{"item_group": g, "brand": BRAND, "priority": 1} for g in groups])

	def calculate(self, **inputs):
		return calculate(self.template.name, {**offgrid.load_totals(load_rows()), **inputs})

	def test_the_golden_load_table_gives_the_files_needs(self):
		totals = offgrid.load_totals(load_rows())
		self.assertEqual(totals, {"load_w": 3170, "day_wh": 25560, "night_wh": 13990})
		need = offgrid.needs(self.calculate().inputs)
		self.assertAlmostEqual(need["panel_w"], 7190.909, places=3)
		self.assertAlmostEqual(need["inverter_kw"], 4.755, places=3)
		self.assertAlmostEqual(need["battery_ah"], 404.803, places=3)

	def test_the_products_round_up(self):
		result = self.calculate()
		lines = {line.line_key: line for line in result.lines}
		self.assertEqual((lines["panels"].item_code, lines["panels"].qty), (self.items["panel"].name, 8750))
		self.assertEqual(lines["inverter"].item_code, self.items["inv5"].name)  # smallest at or above 4.755
		self.assertEqual((lines["batteries"].item_code, lines["batteries"].qty), (self.items["bat"].name, 3))
		self.assertEqual((lines["dc_cable"].qty, lines["mc4"].qty), (40, 2))  # two strings, as in the file
		self.assertAlmostEqual(lines["installation"].qty, 8.75)
		notes = {
			n["line_key"]: n["message"]
			for n in result.rule_results
			if n["line_key"] in ("panels", "batteries")
		}
		self.assertIn("7190.9", notes["panels"])
		self.assertIn("404.8", notes["batteries"])

	def test_the_quote_creator_can_set_the_strings(self):
		lines = {line.line_key: line for line in self.calculate(strings=3).lines}
		self.assertEqual(lines["panels"].qty, 3 * 7 * 625)

	def test_a_draft_takes_the_request_load_table(self):
		case = frappe.get_doc({"doctype": "SP Case", "loads": load_rows()})
		inputs = request_inputs(case, self.template.name)
		self.assertEqual(
			{k: inputs[k] for k in offgrid.LOAD_INPUTS}, {"load_w": 3170, "day_wh": 25560, "night_wh": 13990}
		)

	def test_each_component_carries_its_warranty_and_the_quote_may_change_it(self):
		quote = frappe.new_doc("Quotation")
		write_lines(quote, self.calculate())
		years = {row.sp_line_key: row.sp_warranty_years for row in quote.items}
		self.assertEqual((years["panels"], years["inverter"], years["batteries"]), (25, 3, 7))
		next(row for row in quote.items if row.sp_line_key == "batteries").sp_warranty_years = 10
		write_lines(quote, self.calculate())
		years = {row.sp_line_key: row.sp_warranty_years for row in quote.items}
		self.assertEqual(years["batteries"], 10)  # kept while the line keeps its item


class TestOffgridVoltage(IntegrationTestCase):
	"""BUG-25: the inverter and the batteries are for the battery bank's voltage."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_item_groups()
		if not frappe.db.exists("Brand", BRAND):
			frappe.get_doc({"doctype": "Brand", "brand": BRAND}).insert()

		def item(code, group, **specs):
			doc = make_item(code, item_group=group, brand=BRAND, **specs)
			for key in (COST, BTC):
				prices.set_price(doc.name, key, DEMO_PRICE, reason="BUG-25 test")
			return doc.name

		cls.panel = item("BUG25-PANEL-625", PANELS, sp_watt=625)
		cls.inv24 = item("BUG25-INV-5KW-24V", INVERTERS, sp_kw=5, sp_system_voltage=24)
		cls.inv48 = item("BUG25-INV-6KW-48V", INVERTERS, sp_kw=6, sp_system_voltage=48)
		cls.inv_unset = item("BUG25-INV-5.5KW", INVERTERS, sp_kw=5.5)
		cls.bat24 = item("BUG25-BAT-200AH-24V", BATTERIES, sp_battery_ah=200, sp_system_voltage=24)
		cls.bat48 = item("BUG25-BAT-200AH-48V", BATTERIES, sp_battery_ah=200, sp_system_voltage=48)
		shipped = template_data("offgrid.json")
		cls.template = make_template(inputs=shipped["inputs"], lines=shipped["lines"])

	def setUp(self):
		groups = (PANELS, INVERTERS, BATTERIES)
		set_setting(brand_priorities=[{"item_group": g, "brand": BRAND, "priority": 1} for g in groups])

	def picks(self, voltage):
		lines = calculate(
			self.template.name, {**offgrid.load_totals(load_rows()), "battery_voltage": voltage}
		).lines
		return {line.line_key: line.item_code for line in lines}

	def test_a_48_v_bank_gets_a_48_v_inverter_and_batteries(self):
		picked = self.picks(48)
		# the 5 kW one is smaller, but it is for 24 V; the 5.5 kW one has no voltage set
		self.assertEqual((picked["inverter"], picked["batteries"]), (self.inv48, self.bat48))

	def test_a_24_v_bank_gets_the_24_v_ones(self):
		picked = self.picks(24)
		self.assertEqual((picked["inverter"], picked["batteries"]), (self.inv24, self.bat24))

	def test_an_item_with_no_voltage_comes_after_and_is_flagged(self):
		from smart_power.sp_quotes.engine import ranked_items

		self.assertEqual(
			[c for c in ranked_items(INVERTERS, "kw", 5, voltage=48) if c.startswith("BUG25")],
			[self.inv48, self.inv_unset],
		)

	def test_the_patch_reads_the_voltage_from_the_name(self):
		from smart_power.patches.bug25_system_voltage import voltage_in

		self.assertEqual(voltage_in("LIVOLTEK Lithium Battery, 51.2V , 200AH"), 48)
		self.assertEqual(voltage_in("Pure sine wave solar inverter 1.6kw,12V , 230VAC ,50HZ"), 12)
		self.assertEqual(voltage_in("DYNESS Lithium Battery (DL 2.5), 25.6V , 100AH"), 24)
		self.assertEqual(voltage_in("منظم شحن ماست 50 امبير 48 فولت"), 48)
		self.assertIsNone(voltage_in("منظم شحن 30 امبير 12/24 فولت"))  # a range: the admin sets it
		self.assertIsNone(voltage_in("انفرتر VACON 110 KW - 205 A"))
