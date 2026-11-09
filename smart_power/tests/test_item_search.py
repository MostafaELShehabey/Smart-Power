"""Item search by words in any order (SP-29)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_stock.item_search import item_query, split_words, with_name_filter
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()


def names(rows):
	return {row[0] for row in rows}


def search(txt, filters=None):
	return names(item_query("Item", txt, "name", 0, 20, filters or {}))


class TestItemSearch(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for code, name_ar, name_en in (
			("PNL-RISEN-710-S", "لوح RISEN 710 وات", "RISEN 710 W"),
			("PNL-JA-625-S", "لوح JA 625 وات", "JA 625 W"),
			("PMP-FERAT-110-S", "طلمبة FERAT 110 حصان", "FERAT pump 110 HP"),
		):
			if not frappe.db.exists("Item", code):
				frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": code,
						"item_name": name_en,
						"sp_name_ar": name_ar,
						"item_group": "_Test Item Group",
						"stock_uom": "_Test UOM",
					}
				).insert()

	def test_acceptance_words_with_a_gap(self):
		# typing "لوح 710" finds RISEN 710 W, though "RISEN" sits between the words
		self.assertEqual(search("لوح 710"), {"PNL-RISEN-710-S"})

	def test_words_in_any_order(self):
		self.assertEqual(search("710 لوح"), {"PNL-RISEN-710-S"})

	def test_words_across_fields(self):
		# "FERAT" is in the code and names, "حصان" only in the Arabic name
		self.assertEqual(search("FERAT حصان"), {"PMP-FERAT-110-S"})

	def test_one_word_is_erpnexts_own_search(self):
		self.assertTrue({"PNL-RISEN-710-S", "PNL-JA-625-S"} <= search("لوح"))

	def test_no_match(self):
		self.assertEqual(search("لوح 999"), set())

	def test_erpnext_filters_still_apply(self):
		frappe.db.set_value("Item", "PNL-JA-625-S", "is_sales_item", 0)
		self.assertEqual(search("لوح 625", {"is_sales_item": 1}), set())
		self.assertEqual(search("لوح 625", {"is_sales_item": 0}), {"PNL-JA-625-S"})

	def test_helpers(self):
		self.assertEqual(split_words(" لوح  %710_ "), ["لوح", "710"])
		self.assertEqual(
			with_name_filter({"is_sales_item": 1}, ["A"]), {"is_sales_item": 1, "name": ["in", ["A"]]}
		)
		self.assertEqual(
			with_name_filter([["Item", "disabled", "=", 0]], ["A"])[-1], ["Item", "name", "in", ["A"]]
		)

	def test_arabic_name_is_a_search_field(self):
		self.assertIn("sp_name_ar", frappe.get_meta("Item").get_search_fields())
		self.assertIn("/assets/smart_power/js/item_search.js", frappe.get_hooks("app_include_js"))
