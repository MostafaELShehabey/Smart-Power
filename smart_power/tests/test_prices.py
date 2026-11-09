"""The price list model (SP-30): four lists, dates, suppliers, tiers, pricing rules and price age."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from smart_power.sp_stock import prices
from smart_power.sp_stock.prices import BTB, BTC, COST, LIST
from smart_power.tests.test_customer import make_customer
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()

GROUP = "_Test Item Group"
UOM = "_Test UOM"
SUPPLIER = "_Test Supplier"
OTHER_SUPPLIER = "_Test Supplier 1"


def make_item(code, **kw):
	if frappe.db.exists("Item", code):
		return frappe.get_doc("Item", code)
	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": code,
			"item_group": GROUP,
			"stock_uom": UOM,
			"sp_main_supplier": SUPPLIER,
			**kw,
		}
	).insert()


def make_category(name, rules=(), **kw):
	if frappe.db.exists("SP Price Category", name):
		frappe.delete_doc("SP Price Category", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "SP Price Category",
			"category_name": name,
			"rules": [
				dict(zip(("target", "base", "adjust_pct", "add_amount"), r, strict=True)) for r in rules
			],
			**kw,
		}
	).insert()


class TestPriceLists(IntegrationTestCase):
	def test_four_price_lists_are_seeded_and_linked(self):
		lists = prices.price_lists()
		self.assertEqual(set(lists), {LIST, COST, BTB, BTC})
		for key, name in lists.items():
			self.assertTrue(frappe.db.exists("Price List", name), key)
		self.assertTrue(frappe.db.get_value("Price List", lists[COST], "buying"))
		self.assertTrue(frappe.db.get_value("Price List", lists[BTC], "selling"))
		self.assertEqual(prices.key_of(lists[BTB]), BTB)
		self.assertIsNone(prices.key_of("Standard Selling"))

	def test_customer_tier_picks_the_price_list(self):
		lists = prices.price_lists()
		person = make_customer(mobile="01005550001")
		self.assertEqual(person.default_price_list, lists[BTC])
		person.sp_tier = "Company"
		person.save()
		self.assertEqual(person.default_price_list, lists[BTB])

	def test_hand_picked_price_list_stays_until_the_tier_changes(self):
		customer = make_customer(mobile="01005550002", default_price_list="Standard Selling")
		self.assertEqual(customer.default_price_list, "Standard Selling")
		customer.customer_name = "renamed"
		customer.save()
		self.assertEqual(customer.default_price_list, "Standard Selling")


class TestSetPrice(IntegrationTestCase):
	def setUp(self):
		# tests in a class share one transaction: each test gets its own item
		self.item = make_item("SP-PRICE-TEST-" + frappe.generate_hash(length=6)).name

	def test_new_price_has_a_date_and_the_main_supplier(self):
		name, changed = prices.set_price(self.item, COST, 870)
		self.assertTrue(changed)
		row = frappe.get_doc("Item Price", name)
		self.assertEqual(
			(row.price_list_rate, row.supplier, getdate(row.valid_from)), (870, SUPPLIER, getdate(today()))
		)

	def test_sale_prices_carry_no_supplier(self):
		name, _changed = prices.set_price(self.item, BTC, 1270, supplier=SUPPLIER)
		self.assertFalse(frappe.db.get_value("Item Price", name, "supplier"))

	def test_buying_price_needs_a_supplier(self):
		item = make_item("SP-PRICE-TEST-NOSUP", sp_main_supplier=None).name
		with self.assertRaises(frappe.ValidationError):
			prices.set_price(item, LIST, 1000)

	def test_one_item_holds_prices_from_several_suppliers(self):
		prices.set_price(self.item, COST, 870, price_date=add_days(today(), -10))
		prices.set_price(self.item, COST, 850, supplier=OTHER_SUPPLIER)
		rows = frappe.get_all(
			"Item Price",
			{"item_code": self.item, "price_list": prices.price_list(COST)},
			pluck="supplier",
		)
		self.assertEqual(sorted(rows), sorted([SUPPLIER, OTHER_SUPPLIER]))
		# the main supplier's price is the item's cost
		self.assertEqual(prices.latest_price(self.item, COST).rate, 870)
		self.assertEqual(prices.latest_price(self.item, COST, supplier=OTHER_SUPPLIER).rate, 850)

	def test_changing_a_price_needs_a_reason_and_moves_the_date(self):
		name, _ = prices.set_price(self.item, BTB, 5200, price_date=add_days(today(), -40))
		with self.assertRaises(frappe.ValidationError):
			prices.set_price(self.item, BTB, 5450)
		same, changed = prices.set_price(self.item, BTB, 5450, reason="supplier raised prices")
		self.assertEqual((same, changed), (name, True))
		row = frappe.get_doc("Item Price", name)
		self.assertEqual((row.price_list_rate, getdate(row.valid_from)), (5450, getdate(today())))
		log = frappe.get_all(
			"SP Edit Reason Log",
			{"reference_doctype": "Item Price", "reference_name": name},
			["old_value", "new_value", "reason", "user"],
		)
		self.assertEqual(
			[(float(r.old_value), float(r.new_value), r.reason) for r in log],
			[(5200, 5450, "supplier raised prices")],
		)

	def test_same_price_on_a_later_date_refreshes_its_age(self):
		name, _ = prices.set_price(self.item, BTC, 1000, price_date=add_days(today(), -40))
		_same, changed = prices.set_price(self.item, BTC, 1000)
		self.assertTrue(changed)
		self.assertEqual(getdate(frappe.db.get_value("Item Price", name, "valid_from")), getdate(today()))
		_same, changed = prices.set_price(self.item, BTC, 1000)
		self.assertFalse(changed)

	def test_editing_the_price_on_the_form_moves_the_date(self):
		name, _ = prices.set_price(self.item, BTC, 1000, price_date=add_days(today(), -5))
		row = frappe.get_doc("Item Price", name)
		row.price_list_rate = 1100
		row.save()
		self.assertEqual(getdate(row.valid_from), getdate(today()))


# Like the sheet's section headers: P1 = List less 13%, BTC = List less 3% plus 300, BTB = BTC less 5%.
SHEET_RULES = (
	("P1 Cost", "List Price", -13, 0),
	("BTC", "List Price", -3, 300),
	("BTB", "BTC", -5, 0),
)


class TestPricingRules(IntegrationTestCase):
	RULES = SHEET_RULES

	def test_derive_prices_like_the_sheet_headers(self):
		rules = [
			frappe._dict(zip(("target", "base", "adjust_pct", "add_amount"), r, strict=True))
			for r in self.RULES
		]
		derived = prices.derive_prices(rules, {LIST: 1000})
		self.assertEqual(derived, {COST: 870, BTC: 1270, BTB: 1206.5})
		self.assertEqual(prices.derive_prices(rules, {LIST: 1000}, step=5)[BTB], 1205)
		# a price given by hand is kept
		self.assertEqual(prices.derive_prices(rules, {LIST: 1000, BTC: 1500})[BTB], 1425)

	def test_rules_cannot_loop_or_repeat(self):
		with self.assertRaises(frappe.ValidationError):
			make_category(
				"_SP loop",
				rules=(("BTB", "BTC", -5, 0), ("BTC", "List Price", 0, 0), ("P1 Cost", "P1 Cost", 0, 0)),
			)
		with self.assertRaises(frappe.ValidationError):
			make_category("_SP repeat", rules=(("BTC", "List Price", -3, 0), ("BTC", "P1 Cost", 10, 0)))
		with self.assertRaises(frappe.ValidationError):
			make_category("_SP circle", rules=(("BTC", "P1 Cost", 10, 0), ("P1 Cost", "BTC", -10, 0)))

	def test_amber_must_come_before_the_limit(self):
		with self.assertRaises(frappe.ValidationError):
			make_category("_SP ages", max_age_days=30, amber_after_days=30)

	def test_list_price_change_reprices_the_item(self):
		category = make_category("_SP inverters", rules=self.RULES).name
		item = make_item("SP-PRICE-TEST-RULES", sp_price_age_category=category).name
		prices.set_price(item, LIST, 1000)
		changed = prices.apply_category_rules(item, reason="list price changed")
		self.assertEqual(changed, {COST: 870, BTC: 1270, BTB: 1206.5})
		self.assertEqual(prices.latest_price(item, COST).supplier, SUPPLIER)
		prices.set_price(item, LIST, 1100, reason="new catalogue")
		changed = prices.apply_category_rules(item, reason="list price changed")
		self.assertEqual(changed[BTC], 1367)

	def test_manual_items_are_skipped(self):
		category = make_category("_SP manual", rules=self.RULES).name
		item = make_item("SP-PRICE-TEST-MANUAL", sp_price_age_category=category, sp_manual_prices=1).name
		prices.set_price(item, LIST, 1000)
		self.assertEqual(prices.apply_category_rules(item, reason="x"), {})


class TestPriceAge(IntegrationTestCase):
	def test_item_takes_its_group_category(self):
		category = make_category("_SP group default").name
		group = frappe.get_doc("Item Group", GROUP)
		group.sp_price_age_category = category
		group.save()
		item = make_item("SP-PRICE-TEST-GROUP")
		self.assertEqual(item.sp_price_age_category, category)

	def test_btc_price_older_than_the_limit_is_stale(self):
		"""Given a BTC price dated 40 days ago in a category with a 30-day limit, it is stale (red)."""
		category = make_category("_SP panels", max_age_days=30, amber_after_days=20).name
		item = make_item("SP-PRICE-TEST-AGE", sp_price_age_category=category).name
		prices.set_price(item, BTC, 1000, price_date=add_days(today(), -40))
		result = prices.get_price(item, "Individual")
		self.assertEqual(
			(result.price, result.age_days, result.is_stale, result.age_status), (1000, 40, True, "stale")
		)

	def test_age_steps(self):
		category = make_category("_SP steps", max_age_days=30, amber_after_days=20).name
		self.assertEqual(prices.age_status(10, category), "fresh")
		self.assertEqual(prices.age_status(25, category), "aging")
		self.assertEqual(prices.age_status(31, category), "stale")
		self.assertEqual(prices.age_status(None, category), "no_price")
		self.assertEqual(prices.age_status(500, make_category("_SP no limit").name), "no_limit")

	def test_tier_and_the_older_of_price_and_cost(self):
		category = make_category("_SP tiers", max_age_days=30).name
		item = make_item("SP-PRICE-TEST-TIER", sp_price_age_category=category).name
		prices.set_price(item, BTC, 1270)
		prices.set_price(item, BTB, 1200)
		prices.set_price(item, COST, 870, price_date=add_days(today(), -35))
		person, company = prices.get_price(item, "Individual"), prices.get_price(item, "Company")
		self.assertEqual((person.price, company.price), (1270, 1200))
		self.assertEqual((person.cost, person.cost_supplier), (870, SUPPLIER))
		# the sale price is fresh but the cost is 35 days old: the margin may be wrong
		self.assertTrue(person.is_stale)

	def test_quotes_use_the_same_helper(self):
		from smart_power.sp_quotes.pricing import get_price

		self.assertIs(get_price, prices.get_price)
