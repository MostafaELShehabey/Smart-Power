"""SP-63 stale prices: a clock on stale lines; at Send, Warn asks for a reason (listed for the
admin), Block stops the send naming the item, Off lets it go."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.sp_quotes.price_age import StalePriceBlocked, StalePriceReasonRequired
from smart_power.sp_quotes.quote_send import send_options, send_quote
from smart_power.sp_stock import prices
from smart_power.sp_stock.prices import BTC, COST
from smart_power.tests.test_prices import UOM, make_category, make_item
from smart_power.tests.test_quotation_case import case_for_test_customer
from smart_power.tests.test_quote_send import blank_pdf
from smart_power.tests.utils import make_quotation

CATEGORY = "SP63 Panels"
STALE_ITEM, FRESH_ITEM = "SP63-PANEL-OLD", "SP63-PANEL-NEW"


class TestQuotePriceAge(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_category(CATEGORY, max_age_days=30, amber_after_days=20, rule_level="Warn")
		for code, days in ((STALE_ITEM, 60), (FRESH_ITEM, 5)):
			make_item(code, sp_price_age_category=CATEGORY)
			for key, rate in ((BTC, 1000), (COST, 900)):
				prices.set_price(code, key, rate, price_date=add_days(today(), -days))

	def setUp(self):
		# CI builds no assets and has no Chromium: the PDF itself is SP-62's (as in test_quote_send)
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		pdf = patch("frappe.get_print", return_value=blank_pdf())
		pdf.start()
		self.addCleanup(pdf.stop)

	def quote(self, item=STALE_ITEM):
		q = make_quotation(save=False, case=case_for_test_customer().name)
		for row in q.items:
			row.item_code, row.item_name, row.uom, row.stock_uom = item, item, UOM, UOM
		return q.insert()

	def set_level(self, level):
		frappe.db.set_value("SP Price Category", CATEGORY, "rule_level", level)
		frappe.clear_document_cache("SP Price Category", CATEGORY)

	def test_the_stale_line_carries_its_age(self):
		q = self.quote()
		self.assertEqual((q.items[0].sp_price_status, q.items[0].sp_price_age_days), ("stale", 60))
		fresh = self.quote(FRESH_ITEM)
		self.assertEqual(fresh.items[0].sp_price_status, "fresh")

	def test_warn_asks_for_a_reason_that_reaches_the_review_centre(self):
		self.set_level("Warn")
		q = self.quote()
		self.assertEqual([r["item_code"] for r in send_options(q.name)["price_age"]["warn"]], [STALE_ITEM])
		with self.assertRaises(StalePriceReasonRequired):
			send_quote(q.name)
		self.assertEqual(frappe.db.get_value("Quotation", q.name, "docstatus"), 0)
		send_quote(q.name, reason="the customer accepted last month's price")
		self.assertEqual(frappe.db.get_value("Quotation", q.name, "docstatus"), 1)
		item = frappe.get_all(
			"SP Review Item", {"reference_name": q.name, "status": "Open"}, ["reason", "summary"]
		)
		self.assertTrue(any(r.reason == "the customer accepted last month's price" for r in item), item)

	def test_block_stops_the_send_naming_the_item(self):
		self.set_level("Block")
		q = self.quote()
		self.assertEqual([r["item_code"] for r in send_options(q.name)["price_age"]["block"]], [STALE_ITEM])
		with self.assertRaises(StalePriceBlocked) as caught:
			send_quote(q.name, reason="anyway")
		self.assertIn(STALE_ITEM, str(caught.exception))
		self.assertEqual(frappe.db.get_value("Quotation", q.name, "docstatus"), 0)

	def test_off_and_fresh_prices_send_without_a_word(self):
		self.set_level("Off")
		q = self.quote()
		self.assertEqual(send_options(q.name)["price_age"], {"block": [], "warn": []})
		send_quote(q.name)
		self.set_level("Warn")
		fresh = self.quote(FRESH_ITEM)
		send_quote(fresh.name)
		self.assertEqual(frappe.db.get_value("Quotation", fresh.name, "docstatus"), 1)
