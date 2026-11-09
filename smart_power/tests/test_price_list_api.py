"""I2 price list screen API (SP-30 acceptance criteria, with the SP-35 cost rule)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.permissions import COST_KEYS
from smart_power.sp_stock import price_list_api as api
from smart_power.sp_stock import prices
from smart_power.sp_stock.prices import BTB, BTC, COST, LIST
from smart_power.tests.test_prices import SHEET_RULES, make_category, make_item
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()


class TestPriceListScreen(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.aya = make_user("sp.i2.aya@example.com", ("quote_creator", "catalog_manager", "pricing_manager"))
		cls.camelia = make_user("sp.i2.camelia@example.com", ("lead_intake", "customer_followup"))
		cls.helper = make_user(
			"sp.i2.helper@example.com", ("showroom_sales",), extra_roles=("Sales Master Manager",)
		)
		cls.panels = make_category("_SP I2 panels", max_age_days=30).name

	def setUp(self):
		code = "SP-I2-" + frappe.generate_hash(length=6)
		self.item = make_item(code, sp_name_ar="لوح اختبار " + code, sp_price_age_category=self.panels).name
		prices.set_price(self.item, COST, 4700)
		prices.set_price(self.item, BTB, 5200)
		prices.set_price(self.item, BTC, 5600, price_date=add_days(today(), -40))

	def tearDown(self):
		frappe.set_user("Administrator")

	def rows(self, **filters):
		return api.get_rows({"search": self.item, **filters})

	def test_btc_older_than_the_category_limit_shows_red(self):
		"""Given a BTC price dated 40 days ago in Panels (limit 30), the row is stale."""
		frappe.set_user(self.camelia)
		row = self.rows()["rows"][0]
		self.assertEqual((row["btc"], row["age_days"], row["age_status"]), (5600, 40, "stale"))
		self.assertEqual(len(self.rows(age_status="stale")["rows"]), 1)
		self.assertEqual(self.rows(age_status="fresh")["rows"], [])

	def test_followup_never_receives_cost(self):
		"""Given كاميليا, when she opens I2, then P1 cost is not in the response."""
		frappe.set_user(self.camelia)
		result = self.rows()
		self.assertFalse(result["sees_cost"])
		self.assertFalse(result["can_edit"])
		self.assertNotIn(COST, result["price_lists"])
		row = result["rows"][0]
		self.assertEqual(row["btb"], 5200)
		for key in COST_KEYS:
			self.assertNotIn(key, row)

	def test_cost_roles_see_cost_and_margin(self):
		frappe.set_user(self.aya)
		result = self.rows()
		self.assertTrue(result["sees_cost"] and result["can_edit"])
		row = result["rows"][0]
		self.assertEqual((row["cost"], row["cost_supplier"]), (4700, "_Test Supplier"))
		self.assertAlmostEqual(row["margin_pct"], 16.1)

	def test_search_by_arabic_name(self):
		frappe.set_user(self.camelia)
		self.assertEqual(api.get_rows({"search": "لوح اختبار " + self.item})["total"], 1)

	def test_change_with_reason_shows_in_history(self):
		"""Given آية updates BTB 5,200 → 5,450 with a reason, History shows it with her name."""
		frappe.set_user(self.aya)
		with self.assertRaises(frappe.ValidationError):
			api.update_prices(self.item, {BTB: 5450})
		result = api.update_prices(self.item, {BTB: 5450}, reason="new supplier list")
		self.assertEqual(result["row"]["btb"], 5450)
		change = next(e for e in api.price_history(self.item) if e["old"] is not None)
		self.assertEqual(
			(change["price_list"], change["old"], change["new"], change["user"], change["reason"]),
			(BTB, 5200, 5450, self.aya, "new supplier list"),
		)

	def test_history_hides_cost_rows_from_sales(self):
		frappe.set_user(self.aya)
		api.update_prices(self.item, {COST: 4800}, reason="supplier raised the price")
		frappe.set_user(self.camelia)
		self.assertNotIn(COST, {e["price_list"] for e in api.price_history(self.item)})
		frappe.set_user(self.aya)
		self.assertIn(COST, {e["price_list"] for e in api.price_history(self.item)})

	def test_sales_cannot_edit(self):
		frappe.set_user(self.camelia)
		with self.assertRaises(frappe.PermissionError):
			api.update_prices(self.item, {BTC: 1}, reason="x")

	def test_price_role_without_cost_cannot_touch_cost(self):
		frappe.set_user(self.helper)
		with self.assertRaises(frappe.PermissionError):
			api.update_prices(self.item, {COST: 1}, reason="x")
		result = api.update_prices(self.item, {BTC: 5700}, reason="showroom price", apply_rules=0)
		self.assertEqual(result["row"]["btc"], 5700)
		self.assertNotIn("cost", result["row"])

	def test_list_price_runs_the_category_rules(self):
		category = make_category("_SP I2 rules", rules=SHEET_RULES).name
		item = make_item("SP-I2-RULES-" + frappe.generate_hash(length=6), sp_price_age_category=category).name
		frappe.set_user(self.aya)
		result = api.update_prices(item, {LIST: 1000})
		self.assertEqual(result["derived"], {COST: 870, BTC: 1270, BTB: 1206.5})
		# a BTC typed by hand is kept, and BTB follows it
		result = api.update_prices(item, {BTC: 1500}, reason="rounded up for the showroom")
		self.assertEqual(result["row"]["btc"], 1500)
		self.assertEqual(result["derived"], {BTB: 1425})

	def test_apply_rules_for_a_category(self):
		category = make_category("_SP I2 bulk", rules=(("BTC", "P1 Cost", 10, 0),)).name
		item = make_item("SP-I2-BULK-" + frappe.generate_hash(length=6), sp_price_age_category=category).name
		prices.set_price(item, COST, 1000)
		frappe.set_user(self.aya)
		with self.assertRaises(frappe.ValidationError):
			api.apply_rules(reason="", category=category)
		self.assertEqual(api.apply_rules(reason="new margins", category=category), {"items": 1, "changed": 1})
		self.assertEqual(prices.latest_price(item, BTC).rate, 1100)


class TestHistoryNumbers(IntegrationTestCase):
	def test_formatted_version_values_are_read_back(self):
		self.assertEqual(api._number("5,500.00 EGP"), 5500)
		self.assertEqual(api._number("-1,234.50"), -1234.5)
		self.assertEqual(api._number(870), 870)
		self.assertIsNone(api._number(""))
