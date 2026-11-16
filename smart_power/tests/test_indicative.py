"""Indicative price (SP-49): the pump template's sale price, the stale clock, price check only."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.sp_core.services.lists import by_code
from smart_power.sp_quotes import indicative
from smart_power.sp_quotes.calc_templates import template_data
from smart_power.sp_stock import prices
from smart_power.sp_stock.item import seed_item_groups
from smart_power.sp_stock.prices import COST
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.test_prices import make_category
from smart_power.tests.test_pump_template import golden, prefer, set_up_items
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

PUMP = "System Type-PUMP"
TEN_HP = {"hp": 10, "pump_depth": 60}


class PumpTemplateCase(IntegrationTestCase):
	"""The golden pump items and a published pump template made from the shipped one."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_item_groups()
		data = golden()
		set_up_items(data)
		shipped = template_data("pump.json")
		groups = {row["item_group"] for row in shipped["lines"] if row.get("item_group")}
		prefer(data["cases"]["40hp"], groups)
		cls.template = make_template(inputs=shipped["inputs"], lines=shipped["lines"])
		cls.template.publish()  # the published pump template for this test class

	def setUp(self):
		frappe.cache.delete_keys("sp_indicative:")


class TestIndicativePrice(PumpTemplateCase):
	def test_form_asks_the_required_inputs(self):
		form = indicative.indicative_form(PUMP)
		self.assertEqual(form["template"], self.template.name)
		self.assertEqual([i.input_key for i in form["inputs"]], ["hp", "pump_depth"])

	def test_ten_hp_pump_gives_a_sale_price_per_kw_and_no_cost(self):
		result = indicative.indicative_price(PUMP, TEN_HP)
		# 10 HP x 0.746 x 1.5 = 11.19 kW -> 2 strings of 15 x 625 W = 18.75 kW
		self.assertEqual(result["plant_kw"], 18.75)
		self.assertGreater(result["total_sell"], 0)
		self.assertAlmostEqual(result["price_per_kw"], result["total_sell"] / 18.75, places=2)
		self.assertNotIn("cost", json.dumps(result, default=str).lower())
		self.assertEqual(result["stale"], [])
		# lines the catalogue cannot price yet are named, so the price is known to be partial
		self.assertIn("مواسير الغاطس", result["missing"])
		# a line of 0 m, or a price without its cost, is not "not priced"
		self.assertNotIn("كابل بحري (القطاع الثاني)", result["missing"])
		self.assertNotIn("GLD40-PMP-40", result["missing"])

	def test_an_old_price_shows_the_clock_with_the_item(self):
		category = make_category("SPT Indicative Stale", max_age_days=30).name
		before = frappe.db.get_value("Item", "GLD40-PNL-625", "sp_price_age_category")
		frappe.db.set_value("Item", "GLD40-PNL-625", "sp_price_age_category", category)
		self.addCleanup(frappe.db.set_value, "Item", "GLD40-PNL-625", "sp_price_age_category", before)
		prices.set_price("GLD40-PNL-625", COST, 8, price_date=add_days(today(), -40), reason="old")
		result = indicative.indicative_price(PUMP, TEN_HP)
		self.assertEqual([s["item_code"] for s in result["stale"]], ["GLD40-PNL-625"])

	def test_the_answer_is_cached_until_a_price_changes(self):
		first = indicative.indicative_price(PUMP, TEN_HP)
		key = indicative.cache_key(self.template.name, TEN_HP)
		self.assertEqual(frappe.cache.get_value(key), first)
		prices.set_price("GLD40-PNL-625", COST, 9.5, reason="new price")
		self.assertNotEqual(indicative.cache_key(self.template.name, TEN_HP), key)

	def test_price_check_only_without_a_mobile(self):
		intake = make_user("sp.indicative.intake@example.com", ("lead_intake",))
		frappe.set_user(intake)
		try:
			name = indicative.price_check_only(PUMP, TEN_HP, channel="Showroom", note="سأل عن السعر فقط")
		finally:
			frappe.set_user("Administrator")
		case = frappe.get_doc("SP Case", name)
		self.assertEqual((case.status, case.customer), ("Lost", None))
		self.assertEqual(case.lost_reason, by_code("Lost Reason", "PRICE_CHECK_ONLY"))
		self.assertEqual((case.requested_by, case.indicative_by), (intake, intake))
		self.assertGreater(case.indicative_price, 0)
		self.assertEqual(frappe.parse_json(case.indicative_specs), TEN_HP)

	def test_price_check_only_with_a_mobile(self):
		with self.assertRaises(frappe.MandatoryError):  # a new mobile needs a name
			indicative.price_check_only(PUMP, TEN_HP, channel="Call", mobile="01004900049")
		name = indicative.price_check_only(
			PUMP, TEN_HP, channel="Call", mobile="01004900049", customer_name="عميل سأل عن السعر"
		)
		customer = frappe.db.get_value("SP Case", name, "customer")
		self.assertEqual(frappe.db.get_value("Customer", customer, "sp_mobile"), "01004900049")
		again = indicative.price_check_only(PUMP, TEN_HP, channel="Call", mobile="01004900049")
		self.assertEqual(frappe.db.get_value("SP Case", again, "customer"), customer)  # found again

	def test_any_other_case_needs_its_customer(self):
		case = frappe.get_doc({"doctype": "SP Case", "channel": "Call", "follow_up_owner": "Administrator"})
		with self.assertRaises(frappe.MandatoryError):
			case.insert()

	def test_price_check_action_needs_the_price_check_reason(self):
		from frappe.model.workflow import get_transitions

		case = frappe.get_doc(
			{
				"doctype": "SP Case",
				"customer": "_Test Customer",
				"channel": "Call",
				"follow_up_owner": "Administrator",
			}
		).insert()
		actions = {t.action for t in get_transitions(case)}
		self.assertNotIn(indicative.PRICE_CHECK_ACTION, actions)

	def test_only_case_creators_price(self):
		user = make_user("sp.indicative.nobody@example.com", ())
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				indicative.indicative_price(PUMP, TEN_HP)
		finally:
			frappe.set_user("Administrator")


class TestIndicativePage(PumpTemplateCase):
	"""IP1 and its hand-over to C3 (SP-49); the pump template set up as above."""

	def test_page_is_for_the_people_who_take_enquiries(self):
		roles = {r.role for r in frappe.get_doc("Page", "sp-indicative-price").roles}
		self.assertEqual(
			roles,
			{"SP Lead Intake", "SP Customer Followup", "SP Marketing Agent", "SP Admin", "System Manager"},
		)

	def test_new_menu_offers_it_to_intake(self):
		from smart_power.shell import get_new_menu

		intake = make_user("sp.indicative.menu@example.com", ("lead_intake",))
		frappe.set_user(intake)
		try:
			keys = [row["key"] for row in get_new_menu()]
		finally:
			frappe.set_user("Administrator")
		self.assertIn("indicative_price", keys)

	def test_quote_request_records_the_indicative_price(self):
		from smart_power.sp_sales.quote_request import create_quote_request

		details = {"hp": 10, "well_depth_m": 120, "water_level_m": 30, "pump_depth_m": 60}
		r = create_quote_request(
			{
				"system_type": PUMP,
				"mobile": "01004900050",
				"customer_name": "عميل من السعر الاسترشادي",
				"channel": "Showroom",
				"details": details,
				"indicative_inputs": TEN_HP,
			}
		)
		case = frappe.get_doc("SP Case", r["case"])
		self.assertEqual(case.status, "Quote request")
		self.assertEqual(case.indicative_price, indicative.indicative_price(PUMP, TEN_HP)["total_sell"])
		self.assertEqual(frappe.parse_json(case.indicative_specs), TEN_HP)
		self.assertEqual(case.indicative_template, self.template.name)
