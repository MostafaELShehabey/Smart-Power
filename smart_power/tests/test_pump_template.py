"""The pump calculation template (SP-56), checked against Mohamed's two sheets.

The golden file (golden/calc_pump_mohamed.json) holds, per case, the sheet's items and prices,
the inputs, the quote creator's edits, the lines the template must give, and the sheet's own
figures. Every line agrees with the sheet within its rounding, except the listed differences.
"""

import json
import os

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_quotes.calc_templates import seed_calc_templates, template_data
from smart_power.sp_quotes.engine import calculate
from smart_power.sp_stock import prices
from smart_power.sp_stock.item import seed_item_groups
from smart_power.sp_stock.prices import BTC, COST, LIST
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.test_prices import make_item
from smart_power.tests.utils import load_erpnext_test_data, set_setting

load_erpnext_test_data()

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "calc_pump_mohamed.json")
SPECS = ("watt", "kw", "hp")
PUMP = "System Type-PUMP"


def golden() -> dict:
	with open(GOLDEN, encoding="utf-8") as f:
		return json.load(f)


def set_up_items(data: dict) -> None:
	"""Every case's items (the cases share the groups), each case under its own brand."""
	for case in data["cases"].values():
		if not frappe.db.exists("Brand", case["brand"]):
			frappe.get_doc({"doctype": "Brand", "brand": case["brand"]}).insert()
		for spec in case["items"]:
			extra = {f"sp_{s}": spec[s] for s in SPECS if s in spec}
			make_item(spec["code"], item_group=spec["group"], brand=case["brand"], **extra)
			for key, field in ((COST, "cost"), (BTC, "btc"), (LIST, "list")):
				if field in spec:
					prices.set_price(spec["code"], key, spec[field], reason="golden file")


def prefer(case: dict, groups: set[str]) -> None:
	"""The case's brand first in every group, as the admin's brand priority would put it."""
	set_setting(
		brand_priorities=[{"item_group": g, "brand": case["brand"], "priority": 1} for g in sorted(groups)]
	)


class TestPumpTemplate(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_item_groups()
		cls.data = golden()
		set_up_items(cls.data)
		shipped = template_data("pump.json")
		cls.groups = {row["item_group"] for row in shipped["lines"] if row.get("item_group")}
		# the shipped lines and inputs, under a key of its own
		cls.template = make_template(inputs=shipped["inputs"], lines=shipped["lines"])

	def run_case(self, name):
		case = self.data["cases"][name]
		prefer(case, self.groups)
		return case, calculate(self.template.name, case["inputs"], case["overrides"])

	def check_case(self, name):
		case, result = self.run_case(name)
		lines = {line.line_key: line for line in result.lines}
		for key, expected in case["expected"]["lines"].items():
			line = lines[key]
			self.assertEqual(line.item_code, expected["item_code"], f"{name} {key}.item_code")
			for field in ("qty", "cost", "rate", "amount", "cost_amount"):
				self.assertAlmostEqual(line[field], expected[field], places=2, msg=f"{name} {key}.{field}")
		for field in ("cost", "sell"):
			self.assertAlmostEqual(result.totals[field], case["expected"]["totals"][field], places=2)
		# the sheet: each line within its rounding, except the listed differences
		tolerance = self.data["tolerance"]
		for key, sheet in case["sheet"]["lines"].items():
			if key in case["differences"]:
				continue
			line = lines[key]
			for field in ("qty", "cost", "rate"):
				self.assertAlmostEqual(
					line[field], sheet[field], places=2, msg=f"{name} {key}.{field} vs sheet"
				)
			for field in ("amount", "cost_amount"):
				self.assertLessEqual(
					abs(line[field] - sheet[field]), tolerance, f"{name} {key}.{field} vs sheet"
				)
		warned = sorted({r["line_key"] for r in result.rule_results if "P1" in r["message"]})
		self.assertEqual(warned, sorted(case["expected"]["cost_warnings"]))
		return result

	def test_100hp_offer(self):
		result = self.check_case("100hp")
		# the whole offer within the sheet's rounding of its line totals
		sheet = self.data["cases"]["100hp"]["sheet"]["totals"]
		self.assertLessEqual(abs(result.totals.sell - sheet["sell"]), self.data["tolerance"])
		self.assertLessEqual(abs(result.totals.cost - sheet["cost"]), self.data["tolerance"])

	def test_40hp_offer_with_the_sheet_errors_corrected(self):
		self.check_case("40hp")

	def test_every_difference_is_explained(self):
		for name, case in self.data["cases"].items():
			for key, reason in case["differences"].items():
				self.assertIn(key, case["sheet"]["lines"], f"{name}: {key}")
				self.assertGreater(len(reason), 40, f"{name}: {key} needs its reason")

	def test_the_inverter_is_never_smaller_than_the_motor(self):
		# without the sheet's pick, a 100 HP pump needs at least 74.6 kW: no 45 kW inverter
		case = self.data["cases"]["100hp"]
		prefer(case, self.groups)
		overrides = {k: v for k, v in case["overrides"].items() if k != "inverter"}
		result = calculate(self.template.name, case["inputs"], overrides)
		inverter = next(line for line in result.lines if line.line_key == "inverter")
		self.assertIsNone(inverter.item_code)
		self.assertIn("inverter", {r["line_key"] for r in result.rule_results})

	def test_strings_from_the_plant_ratio(self):
		# no strings given: 40 HP x 0.746 x 1.5 = 44.76 kW of 625 W panels, 15 a string -> 5 strings
		case = self.data["cases"]["40hp"]
		prefer(case, self.groups)
		inputs = {k: v for k, v in case["inputs"].items() if k != "strings"}
		lines = {line.line_key: line for line in calculate(self.template.name, inputs).lines}
		self.assertEqual((lines["panels"].qty, lines["mc4"].qty, lines["dc_cable"].qty), (46875, 5, 250))

	def test_steel_pipes_and_a_split_cable(self):
		case = self.data["cases"]["100hp"]
		prefer(case, self.groups)
		inputs = {**case["inputs"], "pipe_type": "حديد", "cable_lower_m": 40}
		lines = {line.line_key: line for line in calculate(self.template.name, inputs).lines}
		self.assertEqual(lines["column_pipes"].qty, 22)  # 129 m / 6 m pipes, rounded up
		self.assertEqual((lines["cable"].qty, lines["cable_lower"].qty), (114, 40))  # 129 + 25 - 40

	def test_shipped_template_is_seeded_and_published(self):
		seed_calc_templates()
		name = frappe.db.get_value("SP Calc Template", {"template_key": "PUMP"}, "name")
		self.assertTrue(name)
		doc = frappe.get_doc("SP Calc Template", name)
		self.assertEqual(doc.offer_type, PUMP)
		self.assertEqual(len(doc.lines), len(template_data("pump.json")["lines"]))
		self.assertTrue(frappe.db.exists("SP Calc Template", {"offer_type": PUMP, "is_published": 1}))
		self.assertEqual(seed_calc_templates(), [])  # a second run touches nothing
