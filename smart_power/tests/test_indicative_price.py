"""The indicative price (SP-49, IP1): a sale price from the quote template, never the cost;
"Make quote request" and "Price check only" keep what was shown on the case."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.sp_quotes.engine import calculate
from smart_power.sp_quotes.indicative import indicative_form, indicative_price
from smart_power.sp_sales.price_check import close_price_check
from smart_power.sp_sales.quote_request import create_quote_request, seed_request_fields
from smart_power.sp_stock import prices
from smart_power.sp_stock.prices import BTB, BTC
from smart_power.tests.test_calc_engine import golden, set_up_golden
from smart_power.tests.test_calc_template import PUMP, make_template
from smart_power.tests.test_prices import make_category
from smart_power.tests.utils import load_erpnext_test_data, make_customer, make_user

load_erpnext_test_data()

PANEL_WATT = 600
INPUTS = {"hp": 10, "depth": 99}
PRICE_CHECK = "Lost Reason-PRICE_CHECK_ONLY"
# what the engine knows and the indicative price never returns
HIDDEN = {"cost", "profit", "margin_pct", "lines", "totals", "rule_results"}


def as_user(user, fn, *args, **kw):
	frappe.set_user(user)
	try:
		return fn(*args, **kw)
	finally:
		frappe.set_user("Administrator")


class TestIndicativePrice(IntegrationTestCase):
	def setUp(self):
		seed_request_fields()
		self.data = golden()
		set_up_golden(self.data)
		frappe.db.set_value("Item", "SPT-PANEL", "sp_watt", PANEL_WATT)
		frappe.clear_document_cache("Item", "SPT-PANEL")
		self.template = make_template(**self.data["template"])
		self.template.publish()
		self.camelia = make_user("sp.ip.camelia@example.com", ("lead_intake", "customer_followup"))
		self.maha = make_user("sp.ip.maha@example.com", ("marketing_agent", "lead_intake"))

	def price(self, user=None, **kw):
		return as_user(user or self.camelia, indicative_price, PUMP, kw.pop("inputs", INPUTS), **kw)

	def test_the_form_asks_the_size_and_the_inputs_with_no_default(self):
		form = as_user(self.camelia, indicative_form, PUMP)
		self.assertEqual(form["template"], self.template.name)
		self.assertEqual([i["input_key"] for i in form["inputs"]], ["hp", "depth"])

	def test_sale_price_and_price_per_kw_without_cost(self):
		result = self.price()
		expected = calculate(self.template.name, INPUTS).totals.sell
		self.assertAlmostEqual(result["total_sell"], expected)
		# 10 HP x 2.5 panels per HP = 25 panels x 600 W = 15 kW
		self.assertAlmostEqual(result["kw"], 15)
		self.assertAlmostEqual(result["price_per_kw"], expected / 15)
		self.assertEqual(result["stale_items"], [])
		self.assertFalse(set(result) & HIDDEN)

	def test_company_tier_prices_the_locked_lines_from_btb(self):
		individual = self.price()["total_sell"]
		btc = prices.price_list(BTC)
		for code in ("SPT-MOTOR-A30", "SPT-PIPE", "SPT-CABLE"):  # the locked lines
			rate = frappe.db.get_value(
				"Item Price", {"item_code": code, "price_list": btc}, "price_list_rate"
			)
			prices.set_price(code, BTB, rate - 2000 if code == "SPT-MOTOR-A30" else rate, reason="test")
		self.assertAlmostEqual(individual - self.price(tier="Company")["total_sell"], 2000)

	def test_an_old_price_is_named(self):
		category = make_category("SPT Indicative Stale", max_age_days=30).name
		frappe.db.set_value("Item", "SPT-PIPE", "sp_price_age_category", category)
		prices.set_price("SPT-PIPE", BTC, 365, price_date=add_days(today(), -40), reason="old")
		stale = self.price()["stale_items"]
		self.assertEqual([(s["item_code"], s["age_days"]) for s in stale], [("SPT-PIPE", 40)])

	def test_a_price_change_is_seen_at_once(self):
		before = self.price()["total_sell"]
		prices.set_price("SPT-PIPE", BTC, 460, reason="new price")
		pipes = 33  # ceil(99 / 3)
		self.assertAlmostEqual(self.price()["total_sell"] - before, pipes * 100)

	def test_a_type_without_a_template(self):
		self.template.unpublish()
		with self.assertRaises(frappe.ValidationError):
			self.price()

	def test_the_size_must_be_above_zero(self):
		with self.assertRaises(frappe.ValidationError):
			self.price(inputs={"hp": 0, "depth": 99})

	def test_only_request_takers_use_it(self):
		store = make_user("sp.ip.store@example.com", ("main_store_keeper",))
		with self.assertRaises(frappe.PermissionError):
			self.price(user=store)

	# --- price check only -----------------------------------------------------------------

	def test_price_check_closes_the_enquiry_as_lost(self):
		result = self.price()
		closed = as_user(self.camelia, close_price_check, {"run": result["run"], "channel": "Showroom"})
		case = frappe.get_doc("SP Case", closed["case"])
		self.assertEqual(
			(case.status, case.lost_reason, case.customer, case.channel),
			("Lost", PRICE_CHECK, None, "Showroom"),
		)
		self.assertEqual((case.follow_up_owner, case.requested_by), (self.camelia, self.camelia))
		self.assertAlmostEqual(case.indicative_price, result["total_sell"])
		self.assertEqual((case.indicative_by, case.indicative_template), (self.camelia, self.template.name))
		specs = frappe.parse_json(case.indicative_specs)
		self.assertEqual((specs["hp"], specs["depth"], specs["kw"]), (10, 99, 15))
		self.assertFalse(frappe.get_all("SP Task", {"reference_name": case.name, "status": "Open"}))

	def test_price_check_with_a_name_and_mobile_makes_the_customer(self):
		run = self.price()["run"]
		closed = as_user(
			self.camelia,
			close_price_check,
			{"run": run, "channel": "Call", "mobile": "01007779001", "customer_name": "عميل استفسار"},
		)
		self.assertEqual(frappe.db.get_value("Customer", closed["customer"], "sp_mobile"), "01007779001")

	def test_price_check_keeps_a_mobile_without_a_name_on_the_case(self):
		run = self.price()["run"]
		closed = as_user(
			self.camelia, close_price_check, {"run": run, "channel": "Call", "mobile": "01007779002"}
		)
		self.assertIsNone(closed["customer"])
		self.assertEqual(frappe.db.get_value("SP Case", closed["case"], "mobile"), "01007779002")

	def test_price_check_links_a_returning_customer(self):
		customer = make_customer("01007779003")
		run = self.price()["run"]
		closed = as_user(
			self.camelia, close_price_check, {"run": run, "channel": "Call", "mobile": "01007779003"}
		)
		self.assertEqual(closed["customer"], customer)

	def test_price_check_needs_a_follow_up_user(self):
		run = self.price(user=self.maha)["run"]
		with self.assertRaises(frappe.PermissionError):
			as_user(self.maha, close_price_check, {"run": run, "channel": "Marketing"})

	def test_a_result_is_its_own_users(self):
		run = self.price(user=self.maha)["run"]
		with self.assertRaises(frappe.ValidationError):
			as_user(self.camelia, close_price_check, {"run": run, "channel": "Call"})

	def test_a_price_check_cannot_be_reopened_without_a_customer(self):
		closed = as_user(self.camelia, close_price_check, {"run": self.price()["run"], "channel": "Call"})
		case = frappe.get_doc("SP Case", closed["case"])
		case.status = "Follow-up"
		with self.assertRaises(frappe.MandatoryError):
			case.save()

	# --- make quote request ---------------------------------------------------------------

	def test_the_quote_request_keeps_the_indicative_price(self):
		result = self.price()
		request = {
			"system_type": PUMP,
			"mobile": "01007779004",
			"customer_name": "عميل من السعر الاسترشادي",
			"channel": "Call",
			"details": {"hp": 10, "well_depth_m": 99, "water_level_m": 40, "pump_depth_m": 80},
			"indicative_run": result["run"],
		}
		created = as_user(self.camelia, create_quote_request, request)
		case = frappe.get_doc("SP Case", created["case"])
		self.assertEqual(case.status, "Quote request")
		self.assertAlmostEqual(case.indicative_price, result["total_sell"])
		self.assertEqual(case.indicative_by, self.camelia)

	def test_nobody_types_the_indicative_price(self):
		closed = as_user(self.camelia, close_price_check, {"run": self.price()["run"], "channel": "Call"})
		case = frappe.get_doc("SP Case", closed["case"])
		given = case.indicative_price
		case.indicative_price = 1
		case.lost_note = "ملاحظة"
		case.save()
		self.assertAlmostEqual(frappe.db.get_value("SP Case", case.name, "indicative_price"), given)

	def test_a_case_still_needs_its_customer(self):
		case = frappe.get_doc({"doctype": "SP Case", "channel": "Call", "follow_up_owner": "Administrator"})
		with self.assertRaises(frappe.MandatoryError):
			case.insert()

	def test_page_roles(self):
		roles = {r.role for r in frappe.get_doc("Page", "sp-indicative-price").roles}
		self.assertEqual(
			roles,
			{"SP Lead Intake", "SP Customer Followup", "SP Marketing Agent", "SP Admin", "System Manager"},
		)
