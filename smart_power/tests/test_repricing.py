"""Repricing (SP-170): a sent quote with no confirmed deposit is flagged when it expires or when
its prices change, and the approval of a flagged version follows the old-price rule."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.rules.sales import OLD_PRICE_RULE
from smart_power.sp_quotes.engine import calculate
from smart_power.sp_quotes.quote_calc import write_lines
from smart_power.sp_quotes.repricing import check_quote, check_quotes, differences
from smart_power.sp_sales.quotation import approve_version, new_version
from smart_power.sp_stock import prices
from smart_power.sp_stock.prices import BTC
from smart_power.tests.test_calc_template import make_template
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_quotation_case import case_for_test_customer
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_rule

load_erpnext_test_data()

GROUP = "_Test Item Group"
SENT_DAYS_AGO, RAISED_DAYS_AGO, LISTED_DAYS_AGO = 8, 1, 30


def ago(days):
	return add_days(today(), -days)


class TestRepricing(IntegrationTestCase):
	def setUp(self):
		self.motor = f"SP170-{frappe.generate_hash(length=6).upper()}"
		make_item(self.motor, item_group=GROUP)
		prices.set_price(self.motor, BTC, 1000, price_date=ago(LISTED_DAYS_AGO), reason="listed")
		self.template = make_template(
			inputs=[],
			lines=[
				{
					"line_key": "motor",
					"item_code": self.motor,
					"qty_formula": "2",
					"cost_source": "Per-kW default",
					"pricing_method": "Locked BTC price",
				}
			],
		)
		self.creator = make_user("sp.rp.creator@example.com", ("quote_creator",))
		self.owner = make_user("sp.rp.owner@example.com", ("customer_followup",))
		set_rule(OLD_PRICE_RULE, "Block")

	def sent(self, template=None):
		template = template or self.template
		case = case_for_test_customer()
		frappe.db.set_value(
			"SP Case",
			case.name,
			{"status": "Follow-up", "follow_up_owner": self.owner, "quote_creator": self.creator},
			update_modified=False,
		)
		quote = make_quotation(save=False)
		quote.sp_case = case.name
		quote.sp_quote_creator = self.creator
		quote.sp_calc_template = template.name
		quote.sp_design_inputs = "{}"
		quote.set("items", [])
		write_lines(quote, calculate(template.name, on_date=ago(SENT_DAYS_AGO)))
		quote.insert()
		quote.submit()
		dates = {"transaction_date": ago(SENT_DAYS_AGO), "valid_till": add_days(today(), 3)}
		frappe.db.set_value("Quotation", quote.name, dates, update_modified=False)
		return frappe.get_doc("Quotation", quote.name)

	def raise_price(self, rate=1200):
		prices.set_price(self.motor, BTC, rate, price_date=ago(RAISED_DAYS_AGO), reason="raised")

	def flag(self, quote):
		return frappe.db.get_value("Quotation", quote.name, ["sp_needs_repricing", "sp_status"])

	def test_a_raised_price_flags_the_quote_and_shows_the_difference(self):
		quote = self.sent()
		self.raise_price()
		check_quotes()
		self.assertEqual(self.flag(quote), (1, "Needs repricing"))
		change = differences(frappe.get_doc("Quotation", quote.name))
		self.assertEqual(change["difference"], 400)
		line = change["lines"][0]
		self.assertEqual(
			(line["item_code"], line["old_rate"], line["new_rate"], line["difference"]),
			(self.motor, 1000, 1200, 400),
		)
		self.assertIn(self.motor, frappe.db.get_value("Quotation", quote.name, "sp_repricing_note"))

	def test_an_unchanged_price_is_not_flagged(self):
		quote = self.sent()
		check_quotes()
		self.assertEqual(self.flag(quote), (0, "Sent"))

	def test_a_past_valid_till_is_flagged(self):
		quote = self.sent()
		frappe.db.set_value("Quotation", quote.name, "valid_till", ago(1), update_modified=False)
		self.assertTrue(check_quote(quote.name))
		self.assertEqual(self.flag(quote), (1, "Needs repricing"))

	def test_a_confirmed_deposit_is_never_flagged(self):
		quote = self.sent()
		frappe.db.set_value("SP Case", quote.sp_case, "status", "Won", update_modified=False)
		self.raise_price()
		check_quotes()
		self.assertEqual(self.flag(quote)[0], 0)

	def test_a_lost_case_is_not_flagged(self):
		quote = self.sent()
		frappe.db.set_value("SP Case", quote.sp_case, "status", "Lost", update_modified=False)
		self.raise_price()
		self.assertFalse(check_quote(quote.name))

	def test_an_older_version_is_left_alone(self):
		quote = self.sent()
		new_version(quote.name)
		self.raise_price()
		check_quotes()
		self.assertEqual(self.flag(quote)[0], 0)

	def test_a_discount_on_the_total_is_not_a_price_change(self):
		quote = self.sent()
		frappe.db.set_value("Quotation", quote.name, "discount_amount", 150, update_modified=False)
		self.assertFalse(differences(frappe.get_doc("Quotation", quote.name))["lines"])

	def test_new_stock_on_another_item_is_not_a_price_change(self):
		other = f"SP170-{frappe.generate_hash(length=6).upper()}"
		frappe.db.set_value("Item", self.motor, "sp_hp", 10)
		make_item(other, item_group=GROUP, sp_hp=20)
		prices.set_price(other, BTC, 5000, price_date=ago(LISTED_DAYS_AGO), reason="listed")
		frappe.db.set_value(
			"Item", {"item_group": GROUP, "name": ("not in", [self.motor, other])}, "disabled", 1
		)
		template = make_template(
			inputs=[],
			lines=[
				{
					"line_key": "motor",
					"selection_rule": "Stock first",
					"item_group": GROUP,
					"capacity_field": "hp",
					"need_formula": "1",
					"qty_formula": "1",
					"cost_source": "Per-kW default",
					"pricing_method": "Locked BTC price",
				}
			],
		)
		quote = self.sent(template)
		self.assertEqual(quote.items[0].item_code, self.motor)
		frappe.get_doc(
			{"doctype": "Bin", "item_code": other, "warehouse": "_Test Warehouse - _TC", "actual_qty": 5}
		).insert()
		self.assertFalse(differences(frappe.get_doc("Quotation", quote.name))["lines"])

	def test_the_creator_and_the_owner_are_told_once(self):
		quote = self.sent()
		self.raise_price()
		check_quotes()
		check_quotes()
		told = frappe.get_all(
			"Notification Log",
			{"document_name": quote.name, "sp_event": "quote_needs_repricing"},
			pluck="for_user",
		)
		self.assertEqual(sorted(told), sorted([self.creator, self.owner]))

	def flagged(self):
		quote = self.sent()
		self.raise_price()
		check_quote(quote.name)
		return quote

	def test_block_forces_a_new_version(self):
		quote = self.flagged()
		with self.assertRaises(frappe.ValidationError):
			approve_version(quote.name, reason="عميل قديم")

	def test_warn_lets_the_admin_honor_the_old_price_with_a_reason(self):
		set_rule(OLD_PRICE_RULE, "Warn")
		quote = self.flagged()
		with self.assertRaises(frappe.ValidationError):
			approve_version(quote.name)
		approve_version(quote.name, reason="عميل قديم")
		self.assertEqual(self.flag(quote), (0, "Approved"))
		self.assertTrue(
			frappe.db.exists("SP Rule Hit", {"rule": OLD_PRICE_RULE, "reference_name": quote.name})
		)

	def test_warn_is_for_the_admin_only(self):
		set_rule(OLD_PRICE_RULE, "Warn")
		quote = self.flagged()
		frappe.set_user(self.creator)
		try:
			with self.assertRaises(frappe.ValidationError):
				approve_version(quote.name, reason="عميل قديم")
		finally:
			frappe.set_user("Administrator")
