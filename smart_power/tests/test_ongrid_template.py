"""The on-grid calculation template and the grid-connection tasks (SP-173), checked against the
owner's on-grid 100 kW offer (30-7-2026).

The file's lines, with its two errors corrected: 625 W x 18 x 9 = 101.25 kW (the title said 125 kW
and the panel text 715 W). The sale price is the cost / 0.86. The costs here are demo numbers,
not the file's.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_core.services.lists import by_code
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_quotes.calc_templates import template_data
from smart_power.sp_quotes.engine import calculate
from smart_power.sp_stations import task_templates as tt
from smart_power.sp_stock import prices
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock.item import seed_item_groups
from smart_power.sp_stock.prices import COST
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.test_prices import make_item
from smart_power.tests.utils import load_erpnext_test_data, make_test_case, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"  # CI has no default company
BRAND = "SP173 Brand"
PANELS, INVERTERS = "ألواح شمسية", "إنفرترات ودرايفات"
FACTOR = 0.86  # the file's sale factor
DEMO_COSTS = {"chassis": 100, "ac_cable": 50, "dc_cable": 5, "mc4": 4, "pipes_2in": 20, "flex": 40}
DEMO_COSTS |= {"installation": 25, "earthing": 1000, "technical_file": 300, "transport": 3000}
PANEL_COST, INVERTER_COST = 1, 9000  # demo prices: per watt, and the inverter
PIASTRE = 0.01  # a rate rounds to 2 decimals


class TestOngridTemplate(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_item_groups()
		wh.seed_warehouses(COMPANY)  # a station opens its site warehouse
		seed_centers(COMPANY)
		if not frappe.db.exists("Brand", BRAND):
			frappe.get_doc({"doctype": "Brand", "brand": BRAND}).insert()
		cls.panel = make_item("SP173-PANEL-625", item_group=PANELS, brand=BRAND, sp_watt=625).name
		cls.inverter = make_item("SP173-INV-80KW", item_group=INVERTERS, brand=BRAND, sp_kw=80).name
		prices.set_price(cls.panel, COST, PANEL_COST, reason="SP-173 test")
		prices.set_price(cls.inverter, COST, INVERTER_COST, reason="SP-173 test")
		shipped = template_data("ongrid.json")
		cls.template = make_template(inputs=shipped["inputs"], lines=shipped["lines"])

	def setUp(self):
		set_setting(brand_priorities=[{"item_group": PANELS, "brand": BRAND, "priority": 1}])

	def calculate(self, **overrides):
		costs = {key: {"cost": cost} for key, cost in DEMO_COSTS.items()}
		return calculate(self.template.name, {"kw": 100}, {**costs, **overrides})

	def test_100_kw_reproduces_the_files_lines(self):
		lines = {line.line_key: line for line in self.calculate().lines}
		self.assertEqual((lines["panels"].item_code, lines["panels"].qty), (self.panel, 101250))  # 101.25 kW
		expected = {"chassis": 101.25, "ac_cable": 3, "dc_cable": 720, "mc4": 9, "pipes_2in": 18, "flex": 18}
		expected |= {"installation": 101.25, "earthing": 1, "technical_file": 1, "transport": 1}
		self.assertEqual({key: flt(lines[key].qty, 2) for key in expected}, expected)
		self.assertEqual(lines["fittings"].cost, 18 * DEMO_COSTS["flex"] / 4)  # a quarter of the flexible

	def test_the_sale_price_is_the_cost_over_the_factor(self):
		result = self.calculate(inverter={"item_code": self.inverter})
		for line in result.lines:
			if line.cost:
				self.assertAlmostEqual(line.rate, line.cost / FACTOR, places=2, msg=line.line_key)
		# each rate rounds to the piastre (the panels per watt), as a quote line's rate is saved
		rounding = sum(line.qty * PIASTRE / 2 for line in result.lines if line.cost)
		self.assertAlmostEqual(result.totals.sell, result.totals.cost / FACTOR, delta=rounding)
		self.assertAlmostEqual(result.totals.margin_pct, 14, delta=0.5)

	def test_the_inverter_waits_for_the_quote_creators_pick(self):
		lines = {line.line_key: line for line in self.calculate().lines}
		self.assertIsNone(lines["inverter"].item_code)
		lines = {line.line_key: line for line in self.calculate(inverter={"item_code": self.inverter}).lines}
		self.assertEqual((lines["inverter"].item_code, lines["inverter"].warranty_years), (self.inverter, 2))

	def test_cost_over_factor_needs_the_factor_input(self):
		shipped = template_data("ongrid.json")
		inputs = [row for row in shipped["inputs"] if row["input_key"] != "sale_factor"]
		with self.assertRaises(frappe.ValidationError):
			make_template(inputs=inputs, lines=shipped["lines"])

	def test_an_on_grid_station_opens_the_grid_connection_tasks_with_their_owners(self):
		tt.seed_task_templates()
		owners = {
			"SP Regulatory Compliance": make_user("sp.grid.aya@example.com", ("regulatory_compliance",)),
			"SP Installation Manager": make_user("sp.grid.install@example.com", ("installation_manager",)),
			"SP Accountant": make_user("sp.grid.accounts@example.com", ("accountant",)),
		}
		case = frappe.get_doc("SP Case", make_test_case())
		case.append("system_types", {"system_type": by_code("System Type", "ONGRID")})
		case.save(ignore_permissions=True)
		station = frappe.get_doc({"doctype": "SP Station", "case": case.name, "company": COMPANY}).insert(
			ignore_permissions=True
		)
		tasks = frappe.get_all(
			"SP Task",
			{
				"reference_doctype": "SP Station",
				"reference_name": station.name,
				"task_type": "Grid Connection",
			},
			["subject", "assigned_to"],
		)
		steps = frappe.get_doc(tt.TEMPLATE, "ربط على الشبكة (صافي القياس)").steps
		for step in steps:
			mine = [t for t in tasks if t.subject == step.subject]
			self.assertIn(owners[step.owner_role], {t.assigned_to for t in mine}, step.subject)
		aya = [t for t in tasks if t.assigned_to == owners["SP Regulatory Compliance"]]
		self.assertEqual(len(aya), 2)  # both of her steps, not one

	def test_a_pump_station_gets_no_grid_tasks(self):
		tt.seed_task_templates()
		case = frappe.get_doc("SP Case", make_test_case())
		case.append("system_types", {"system_type": by_code("System Type", "PUMP")})
		case.save(ignore_permissions=True)
		station = frappe.get_doc({"doctype": "SP Station", "case": case.name, "company": COMPANY}).insert(
			ignore_permissions=True
		)
		self.assertFalse(
			frappe.db.exists("SP Task", {"reference_name": station.name, "task_type": "Grid Connection"})
		)
