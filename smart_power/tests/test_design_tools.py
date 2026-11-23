"""T1 Design tools (SP-65): the string check against the drive, the pump selector on the curves,
the off-grid sizing of a load table, and "Push to quote" into the quote's design inputs."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_quotes import builder, design
from smart_power.sp_quotes.calc_templates import seed_calc_templates
from smart_power.sp_stock.item import seed_item_groups
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_pump_template import golden, prefer, set_up_items
from smart_power.tests.utils import load_erpnext_test_data, make_customer, make_user, set_setting

load_erpnext_test_data()

PUMP = "System Type-PUMP"
PANEL = {"sp_watt": 710, "sp_vmp": 41.6, "sp_voc": 49.5, "sp_isc": 18.2}
DRIVE = {"sp_kw": 30, "sp_max_dc_v": 800, "sp_mppt_min": 200, "sp_mppt_max": 750}


def curve(*points):
	return [{"flow_m3h": f, "head_m": h} for f, h in points]


class TestDesignTools(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_item_groups()
		seed_calc_templates()
		cls.data = golden()
		set_up_items(cls.data)
		cls.sample = next(iter(cls.data["cases"].values()))
		shipped = frappe.get_all(
			"SP Calc Template Line", {"parenttype": "SP Calc Template"}, pluck="item_group"
		)
		prefer(cls.sample, {g for g in shipped if g})
		cls.panel = make_item("SP65-PANEL-710", **PANEL).name
		cls.cool = make_item("SP65-PANEL-COOL", **PANEL, sp_temp_coeff_voc=-0.25).name
		cls.drive = make_item("SP65-DRIVE-30", **DRIVE).name
		cls.small_drive = make_item("SP65-DRIVE-15", **{**DRIVE, "sp_kw": 15}).name
		# head at 30 m³/h: 100 m (covers 90), 80 m (short), and no reading (its curve ends at 25)
		cls.fits = make_item("SP65-PUMP-A", sp_hp=30, sp_curve_points=curve((20, 120), (40, 80))).name
		cls.short = make_item("SP65-PUMP-B", sp_hp=25, sp_curve_points=curve((20, 100), (40, 60))).name
		cls.ends = make_item("SP65-PUMP-C", sp_hp=20, sp_curve_points=curve((5, 150), (25, 95))).name
		cls.aya = make_user("sp.dt.aya@example.com", ("quote_creator", "system_designer"))
		cls.camelia = make_user("sp.dt.camelia@example.com", ("followup_all",))
		cls.owner = make_user("sp.dt.owner@example.com", ("lead_intake", "customer_followup"))
		cls.customer = make_customer("01009990652", "عميل أدوات التصميم")

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def check(self, panel=None, n=18, strings=2, tmin=5, tmax=45):
		return design.string_check(panel or self.panel, n, strings, self.drive, tmin, tmax)

	def test_eighteen_710_w_panels_at_5_degrees_fail_the_800_v_drive(self):
		result = self.check()
		voc = next(c for c in result["checks"] if c["key"] == "voc")
		self.assertAlmostEqual(voc["value"], 49.5 * 18 * (1 + 0.0029 * 20), places=1)  # 942.7 V
		self.assertFalse(voc["ok"])
		self.assertFalse(result["ok"])
		self.assertEqual(result["coeff"], design.DEFAULT_COEFF)  # the panel has none

	def test_fourteen_panels_pass_every_check_and_give_the_kwp(self):
		result = self.check(n=14)
		self.assertTrue(result["ok"], result["checks"])
		self.assertAlmostEqual(result["kwp"], 0.71 * 14 * 2)
		hot = next(c for c in result["checks"] if c["key"] == "vmp_hot")
		self.assertAlmostEqual(hot["value"], 41.6 * 14 * (1 - 0.0029 * 20), places=1)
		self.assertEqual(self.check(self.cool, n=14)["coeff"], -0.25)  # the panel's own coefficient

	def test_a_hot_day_below_the_mppt_minimum_fails(self):
		result = self.check(n=5, tmax=70)
		self.assertFalse(next(c for c in result["checks"] if c["key"] == "vmp_hot")["ok"])

	def test_only_the_pumps_whose_curve_covers_the_duty_are_listed(self):
		result = design.select_pumps(90, 30)
		listed = {p["item"]: p for p in result["pumps"]}
		self.assertIn(self.fits, listed)
		self.assertNotIn(self.short, listed)
		self.assertNotIn(self.ends, listed)
		pump = listed[self.fits]
		self.assertEqual(pump["head_at_flow"], 100)
		self.assertAlmostEqual(pump["drive_kw"], 30 * 0.746, places=2)
		drives = [d["item"] for d in pump["drives"]]
		self.assertIn(self.drive, drives)
		self.assertNotIn(self.small_drive, drives)  # 15 kW is under the 22.4 kW need

	def test_a_load_table_sizes_the_panels_inverter_and_batteries(self):
		loads = [{"load": "إضاءة", "qty": 2, "watts": 100, "day_hours": 6, "night_hours": 4}]
		result = design.size_offgrid(loads)
		self.assertEqual((result["load_w"], result["day_wh"], result["night_wh"]), (200, 1200, 800))
		f = result["factors"]
		self.assertAlmostEqual(result["panel_w"], 2000 / f["sun_hours"])
		self.assertAlmostEqual(result["inverter_kw"], 200 * f["inverter_factor"] / 1000)
		ah = 800 / (f["battery_efficiency"] * f["depth_of_discharge"] * f["battery_voltage"])
		self.assertAlmostEqual(result["battery_ah"], ah)
		self.assertEqual(result["panels"], result["strings"] * f["panels_per_string"])
		self.assertGreaterEqual(result["panels"] * f["panel_watt"], result["panel_w"])
		self.assertRaises(frappe.ValidationError, design.size_offgrid, [])

	def quote(self):
		set_setting(margin_ranges=[{"scope": "Supply and install", "min_pct": 9, "max_pct": 11}])
		case = frappe.get_doc(
			{
				"doctype": "SP Case",
				"customer": self.customer,
				"channel": "Call",
				"follow_up_owner": self.owner,
				"quote_creator": self.aya,
				"system_types": [{"system_type": PUMP}],
				"request_details": {"hp": 20, "well_depth_m": 120, "water_level_m": 40, "pump_depth_m": 100},
			}
		).insert()
		return builder.start(case.name)["quotation"]

	def test_push_writes_the_design_inputs_and_recalculates_the_quote(self):
		name = self.quote()
		frappe.set_user(self.aya)
		before = frappe.db.get_value("Quotation", name, "modified")
		result = design.push(name, "pump", {"head": 90, "flow": 30, "pump": self.fits})
		self.assertEqual(result["pushed"], ["hp", "required_flow_m3h", "required_head_m"])
		doc = frappe.get_doc("Quotation", name)
		inputs = frappe.parse_json(doc.sp_design_inputs)
		self.assertEqual((flt(inputs["required_head_m"]), flt(inputs["hp"])), (90, 30))
		self.assertEqual(flt(inputs["pump_depth"]), 100)  # the request's other inputs stay
		self.assertNotEqual(doc.modified, before)
		page = builder.load(name)
		self.assertEqual(flt({i["input_key"]: i["value"] for i in page["inputs"]}["required_flow_m3h"]), 30)
		pushed = design.push(
			name,
			"string",
			{"panel": self.panel, "n": 14, "strings": 3, "drive": self.drive, "tmin": 5, "tmax": 45},
		)
		self.assertEqual(pushed["pushed"], ["panel_watt", "panels_per_string", "strings"])
		line = frappe.db.get_value(
			"Quotation Item", {"parent": name, "sp_line_key": "panels"}, ["qty", "item_code"], as_dict=True
		)
		watt = flt(frappe.db.get_value("Item", line.item_code, "sp_watt")) or 710
		self.assertEqual(flt(line.qty), 14 * 3 * watt)  # the quote's lines follow the pushed string

	def test_a_failed_check_or_a_wrong_template_is_not_pushed(self):
		name = self.quote()
		frappe.set_user(self.aya)
		failing = {"panel": self.panel, "n": 18, "strings": 2, "drive": self.drive, "tmin": 5, "tmax": 45}
		self.assertRaises(frappe.ValidationError, design.push, name, "string", failing)
		loads = [{"qty": 1, "watts": 500, "day_hours": 5, "night_hours": 2}]
		self.assertRaises(frappe.ValidationError, design.push, name, "offgrid", {"loads": loads})

	def test_only_the_design_roles_use_the_tools(self):
		name = self.quote()
		frappe.set_user(self.camelia)
		self.assertRaises(frappe.PermissionError, design.catalogue)
		self.assertRaises(frappe.PermissionError, design.push, name, "pump", {"head": 90, "flow": 30})
		frappe.set_user(self.aya)
		self.assertIn(self.panel, [p["name"] for p in design.catalogue()["panels"]])
