"""Calibration report (SP-183): the estimate frozen with the approved quote against what the closed
stations used and cost, per template line, with suggested defaults and a draft version."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_quotes import calibration as cal
from smart_power.sp_quotes.calc_templates import seed_calc_templates
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock.item import seed_item_groups
from smart_power.tests.utils import (
	load_erpnext_test_data,
	make_quotation,
	make_user,
	set_setting,
	sign_contract,
)

load_erpnext_test_data()

COMPANY, ITEM, STORE = "_Test Company", "_Test Item", "_Test Warehouse - _TC"
CABLE_PER_STRING, CABLE_EST, KW, LABOUR_COST = 50, 100, 10, 300
USED = (120, 110, 130, 120, 120)  # metres of DC cable used on the five stations: 20% over
LABOUR_PAID = 3600  # each station's site labour: 20% over 10 kW x 300


def line(key, **kw):
	return frappe._dict(
		{"line_key": key, "item_group": None, "calibration_source": None, "calibration_group": None, **kw}
	)


class TestAllocation(IntegrationTestCase):
	def test_an_issue_goes_to_its_own_item_first_then_to_its_group(self):
		lines = [line("cable", item_group="كابلات"), line("cable_lower", item_group="كابلات")]
		quote = [
			{"line_key": "cable", "item_code": "CAB-16", "stock_qty": 100, "cost": 1000},
			{"line_key": "cable_lower", "item_code": "CAB-10", "stock_qty": 20, "cost": 150},
		]
		issues = [
			{"item_code": "CAB-10", "item_group": "كابلات", "qty": 25, "amount": 190},
			{"item_code": "CAB-25", "item_group": "كابلات", "qty": 90, "amount": 1100},  # another size
		]
		out = cal.allocate(lines, quote, issues, {})
		self.assertEqual((out["cable_lower"]["act_qty"], out["cable"]["act_qty"]), (25, 90))

	def test_a_cost_source_is_shared_by_estimated_cost(self):
		lines = [
			line("installation", calibration_source=cal.LABOUR),
			line("wiring", calibration_source=cal.LABOUR),
		]
		quote = [
			{"line_key": "installation", "stock_qty": 10, "cost": 3000},
			{"line_key": "wiring", "stock_qty": 1, "cost": 1000},
		]
		out = cal.allocate(lines, quote, [], {"labour": 6000})
		self.assertEqual((out["installation"]["act_cost"], out["wiring"]["act_cost"]), (4500, 1500))

	def test_a_calibrated_input_without_a_group_asks_for_the_group(self):
		template = frappe._dict(
			inputs=[frappe._dict(input_key="pipes_per_string", default_value="2")],
			lines=[line("pipes", calibration_input="pipes_per_string", description=None, cost_default=0)],
		)
		row = cal.summarise(template, [], 5)[0]
		self.assertEqual(row["source"], cal.ITEMS)
		self.assertEqual(row["note"], "Set the calibration item group on the line.")

	def test_a_line_not_calibrated_is_left_out(self):
		out = cal.allocate([line("fittings")], [{"line_key": "fittings", "stock_qty": 1, "cost": 9}], [], {})
		self.assertEqual(out, {})


class TestCalibration(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_item_groups()
		seed_calc_templates()
		cls.template = frappe.db.get_value(cal.TEMPLATE, {"template_key": "PUMP"}, "name")
		group = frappe.db.get_value("Item", ITEM, "item_group")
		dc = frappe.db.get_value(cal.LINE, {"parent": cls.template, "line_key": "dc_cable"})
		frappe.db.set_value(cal.LINE, dc, "calibration_group", group)  # the admin's group for DC cable
		cls.admin = make_user("sp.cal.admin@example.com", ("admin",))
		cls.creator = make_user("sp.cal.creator@example.com", ("quote_creator",))
		frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"company": COMPANY,
				"items": [{"item_code": ITEM, "qty": sum(USED), "t_warehouse": STORE, "basic_rate": 10}],
			}
		).submit()
		cls.stations = [cls.closed_station(used) for used in USED]

	@classmethod
	def closed_station(cls, used):
		quote = make_quotation(rate=20000, valid_days=3)
		quote.submit()
		approve_version(quote.name)
		frappe.db.set_value("Quotation", quote.name, "sp_calc_template", cls.template)
		for key, qty, cost in (("dc_cable", CABLE_EST, 55), ("installation", KW, LABOUR_COST)):
			frappe.get_doc(
				{
					"doctype": "Quotation Item",
					"parent": quote.name,
					"parenttype": "Quotation",
					"parentfield": "items",
					"item_code": ITEM,
					"item_name": key,
					"qty": qty,
					"stock_qty": qty,
					"uom": "_Test UOM",
					"conversion_factor": 1,
					"sp_line_key": key,
					"sp_cost": cost,
				}
			).db_insert()
		result = make_contract(quote.sp_case)
		sign_contract(result["sales_order"])
		station = frappe.get_doc("SP Station", result["station"])
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Issue",
				"purpose": "Material Issue",
				"company": COMPANY,
				"project": station.project,
				"items": [{"item_code": ITEM, "qty": used, "s_warehouse": STORE, "project": station.project}],
			}
		)
		se.insert()
		se.submit()
		frappe.db.set_value(
			"SP Station", station.name, {"status": "Technically closed", "tech_closed_on": today()}
		)
		return station.name

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_setting(calibration_min_stations=5)
		paid = patch.object(
			cal,
			"actual_cost",
			side_effect=lambda st: {"lines": [{"source": "labour", "amount": LABOUR_PAID}]},
		)
		paid.start()
		self.addCleanup(paid.stop)

	def rows(self, **kw):
		result = cal.report(self.template, kw.get("from_date"), kw.get("to_date"))
		ours = [s for s in result["stations"] if s["station"] in self.stations]
		lines = cal.summarise(frappe.get_doc(cal.TEMPLATE, self.template), ours, cal.min_stations())
		return {r["line_key"]: r for r in lines}

	def test_twenty_percent_over_on_five_stations_suggests_new_defaults(self):
		rows = self.rows()
		dc = rows["dc_cable"]
		self.assertEqual(dc["stations"], 5)
		self.assertAlmostEqual(dc["act_qty"], sum(USED) / 5)
		self.assertAlmostEqual(dc["qty_deviation"], 20)
		self.assertEqual((dc["input"], dc["input_default"]), ("dc_cable_per_string", CABLE_PER_STRING))
		self.assertAlmostEqual(dc["suggested_input"], CABLE_PER_STRING * 1.2)
		installation = rows["installation"]
		self.assertEqual(installation["source"], cal.LABOUR)
		self.assertAlmostEqual(installation["cost_deviation"], 20)
		self.assertAlmostEqual(installation["suggested_cost"], LABOUR_COST * 1.2)
		self.assertEqual(rows["pump"]["stations"], 0)  # no station's quote had a pump line

	def test_a_station_with_no_labour_logged_is_left_out(self):
		paid = {st: LABOUR_PAID for st in self.stations[1:]}  # the first station logged no labour
		with patch.object(
			cal,
			"actual_cost",
			side_effect=lambda st: {"lines": [{"source": "labour", "amount": paid.get(st, 0)}]},
		):
			installation = self.rows()["installation"]
		self.assertEqual((installation["stations"], installation["unrecorded"]), (4, 1))
		self.assertAlmostEqual(installation["cost_deviation"], 20)  # not dragged down by the zero
		self.assertIsNone(installation["suggested_cost"])  # 4 recorded stations are under the 5

	def test_no_suggestion_before_the_minimum_stations(self):
		set_setting(calibration_min_stations=6)
		dc = self.rows()["dc_cable"]
		self.assertIsNone(dc["suggested_input"])
		self.assertIn("6", dc["note"])

	def test_the_period_counts_only_the_stations_closed_in_it(self):
		rows = self.rows(from_date=add_days(today(), -30), to_date=add_days(today(), -1))
		self.assertEqual(rows["dc_cable"]["stations"], 0)

	def test_the_draft_version_holds_the_suggestions_and_the_published_one_is_untouched(self):
		frappe.set_user(self.admin)
		published = frappe.get_doc(cal.TEMPLATE, self.template)
		with patch.object(cal, "station_rows", side_effect=lambda *a: self.mine(*a)):
			name = cal.create_draft(self.template)
		draft = frappe.get_doc(cal.TEMPLATE, name)
		self.assertFalse(draft.is_published)
		self.assertEqual(draft.previous_version, self.template)
		inputs = {r.input_key: r.default_value for r in draft.inputs}
		self.assertEqual(flt(inputs["dc_cable_per_string"]), CABLE_PER_STRING * 1.2)
		cost = {r.line_key: flt(r.cost_default) for r in draft.lines}
		self.assertEqual(cost["installation"], LABOUR_COST * 1.2)
		published.reload()
		self.assertEqual(
			flt({r.input_key: r.default_value for r in published.inputs}["dc_cable_per_string"]),
			CABLE_PER_STRING,
		)

	def mine(self, *args):
		"""station_rows of this test's stations only (the dev site may have closed stations too)."""
		return [s for s in self.original_rows(*args) if s["station"] in self.stations]

	original_rows = staticmethod(cal.station_rows)

	def test_only_the_admin_sees_the_report_and_makes_the_draft(self):
		frappe.set_user(self.creator)
		self.assertRaises(frappe.PermissionError, cal.create_draft, self.template)
		from smart_power.sp_quotes.report.sp_template_calibration import sp_template_calibration as rep

		self.assertRaises(frappe.PermissionError, rep.execute, {"template": self.template})
