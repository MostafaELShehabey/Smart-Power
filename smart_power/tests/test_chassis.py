"""The chassis calculator (SP-166): stands, spacing, rails and parts by each factory's own rules."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_quotes import chassis as ch
from smart_power.sp_quotes import chassis_calc as cc
from smart_power.tests.utils import make_user

AGRI, SHAFEI = "أجري سولار", "علي الشافعي"
# the golden case (the original sheet of 5-11-2026): 7 arrays of 60 JA 625 panels, 30 + 30
GOLDEN_WIDTH, GOLDEN_ARRAYS = 1.13, 7
GOLDEN_RAILS = "3x6 + 3x5 + 1x4"  # the corrected golden file's holder pieces per line
TONGWEI_WIDTH = 1.303  # Agri Solar's worked example: 30 Tongwei 715 panels


def golden(stands=0, layout=GOLDEN_RAILS):
	return [{"panels": 60, "panels_top": 30, "stands": stands, "rail_layout": layout}] * GOLDEN_ARRAYS


class ChassisCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cc.seed_factories()

	def run_calc(self, factory, arrays, width, supports=1, mode=None, **prices):
		f = cc.factory_dict(factory)
		f.update(prices)
		calc = {
			"panel_width": width,
			"panel_watt": 625,
			"rails_mode": mode or f["default_rail_mode"],
			"supports": supports,
			"arrays": arrays,
		}
		result = ch.compute(f, calc)
		result["qty"] = {line["key"]: line["qty"] for line in result["lines"]}
		return result


class TestStands(ChassisCase):
	def test_the_golden_inputs_propose_14_stands_at_about_2_65_m(self):
		for factory in (SHAFEI, AGRI):
			a = self.run_calc(factory, golden(layout=""), GOLDEN_WIDTH)["arrays"][0]
			self.assertAlmostEqual(a["holder_length"], 35.1)
			self.assertEqual(a["proposed_stands"], 14, factory)
			self.assertAlmostEqual(a["spacing"], 2.65, delta=0.025, msg=factory)  # 2.65 or 2.67
			self.assertFalse(a["problems"], factory)

	def test_agri_solar_worked_example_from_its_rules(self):
		r = self.run_calc(AGRI, [{"panels": 30}], TONGWEI_WIDTH)
		a = r["arrays"][0]
		self.assertEqual((a["panels_top"], a["panels_bottom"]), (15, 15))
		self.assertAlmostEqual(a["holder_length"], 20.145)
		self.assertEqual((a["stands"], a["spacing"]), (9, 2.45))
		self.assertAlmostEqual(a["overhang"], 0.545)
		self.assertEqual(a["layout"], [(6, 3), (2.145, 1)])  # 3 whole pieces + one cut to 2.145 m
		q = r["qty"]
		self.assertEqual(
			(q["quad"], q["mid_clamp"], q["end_clamp"], q["bolt_2"], q["base"], q["double"]),
			(12, 56, 8, 156, 18, 36),
		)

	def test_an_overhang_out_of_its_limits_is_flagged(self):
		a = self.run_calc(AGRI, [{"panels": 30, "stands": 9, "spacing": 2.3}], TONGWEI_WIDTH)["arrays"][0]
		self.assertTrue(a["problems"])  # J = 20.145 - 8 x 2.3 = 1.745 m


class TestGolden(ChassisCase):
	def test_15_stands_give_the_corrected_golden_files_iron_and_parts(self):
		r = self.run_calc(SHAFEI, golden(stands=15), GOLDEN_WIDTH)
		q = r["qty"]
		self.assertEqual(r["totals"]["stands"], 105)
		self.assertEqual(
			(q["back_leg"], q["front_leg"], q["support"], q["slant"], q["base"], q["double"]),
			(105, 105, 105, 105, 210, 420),
		)
		self.assertEqual(
			(q["quad"], q["bolt_6"], q["bolt_2"], q["mid_clamp"], q["end_clamp"]), (168, 842, 1934, 812, 56)
		)
		self.assertEqual((q["rail_6"], q["rail_5"], q["rail_4"]), (84, 84, 28))
		self.assertNotIn("support_2", q)  # one support per stand
		self.assertAlmostEqual(r["totals"]["iron_weight_kg"], 3925.16, places=2)

	def test_two_supports_give_6_double_joints_per_stand_and_the_bolts_follow(self):
		r = self.run_calc(SHAFEI, golden(stands=15), GOLDEN_WIDTH, supports=2)
		q = r["qty"]
		self.assertEqual((q["double"], q["support_2"]), (6 * 105, 105))
		self.assertEqual(q["bolt_6"], 105 * 4 + 6 * 105 + 2)
		self.assertEqual(q["bolt_2"], 2 * 210 + 2 * 630 + 4 * 168 + 2)


class TestPrices(ChassisCase):
	def test_excel_rounding_as_in_the_sheets(self):
		self.assertEqual(ch.excel(344.712, -1, ch.ROUND_UP), 350)  # a part's price, up to 10
		self.assertEqual(ch.excel(162.5, -1), 160)
		self.assertEqual(ch.excel(35.2, 0), 35)
		self.assertEqual(ch.excel(12.01, 0, ch.ROUND_UP), 13)

	def test_iron_sells_by_weight_and_an_accessory_by_its_markup(self):
		f = cc.factory_dict(AGRI)
		f.update(iron_cost_kg=100)
		back_leg = next(p for p in f["parts"] if p["key"] == "back_leg")
		cost, kg_sale, sale = ch.price(back_leg, ch.unit_weight(back_leg), f)
		self.assertAlmostEqual(cost, 424)  # 1.6 m x 2.65 kg/m x 100
		self.assertEqual((kg_sale, sale), (125, 530))
		bolt = {**next(p for p in f["parts"] if p["key"] == "bolt_2"), "unit_cost": 3.1}
		self.assertEqual(ch.price(bolt, 0, f)[2], 10)  # 3.1 x 3 = 9.3, up to the pound

	def test_the_showroom_price_list_has_each_part_and_each_holder_length(self):
		rows = cc.price_list(AGRI)
		self.assertEqual(len(rows), len(cc.factory_dict(AGRI)["parts"]) + 3)
		self.assertTrue(any(r["length_m"] == 6 and "حامل" in r["part"] for r in rows))


class TestCalcRecord(ChassisCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.creator = make_user("sp.chassis.creator@example.com", ("quote_creator",))
		cls.admin = make_user("sp.chassis.admin@example.com", ("admin",))

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def calc(self, **kw):
		return frappe.get_doc(
			{
				"doctype": cc.CALC,
				"factory": AGRI,
				"customer_name": "عميل تجربة",
				"panel_width_m": TONGWEI_WIDTH,
				"panel_watt": 715,
				"arrays": [{"panels": 30}],
				**kw,
			}
		)

	def test_the_quote_creator_gets_the_price_analysis_and_cannot_change_the_iron_markup(self):
		frappe.set_user(self.creator)
		doc = self.calc().insert()
		self.assertEqual((doc.stands, doc.review), (9, "✓"))
		self.assertEqual(doc.arrays[0].rails, "4 \u00d7 (3\u00d76 + 1\u00d72.145)")
		self.assertAlmostEqual(doc.capacity_kw, 21.45)
		self.assertTrue(doc.lines)
		self.assertEqual(doc.iron_markup, cc.factory_dict(AGRI)["iron_markup"])
		doc.iron_markup = 2
		with self.assertRaises(frappe.PermissionError):
			doc.save()
		with self.assertRaises(frappe.PermissionError):
			self.calc(iron_markup=2).insert()

	def test_the_stands_and_spacing_in_use_show_and_follow_the_panels_until_typed(self):
		doc = self.calc().insert()
		self.assertEqual((doc.arrays[0].stands, doc.arrays[0].spacing), (9, 2.45))
		doc.arrays[0].panels = 40  # the proposal moves with the panels
		doc.save()
		self.assertEqual(doc.arrays[0].stands, doc.arrays[0].proposed_stands)
		self.assertGreater(doc.arrays[0].stands, 9)
		doc.arrays[0].stands = 15  # a number the creator types stays
		doc.save()
		self.assertEqual(doc.arrays[0].stands, 15)

	def test_the_admin_may_price_one_calc_with_another_markup(self):
		frappe.set_user(self.admin)
		doc = self.calc(iron_markup=1.5).insert()
		self.assertEqual(doc.iron_markup, 1.5)

	def test_a_formula_naming_an_unknown_value_is_refused_on_the_factory(self):
		factory = frappe.get_doc(cc.FACTORY, AGRI)
		factory.parts[0].qty_formula = "stands * legs"
		with self.assertRaises(frappe.ValidationError):
			factory.save()
