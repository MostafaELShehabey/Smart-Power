"""The Arabic customer quote PDF (SP-62)."""

import io
import json
import unittest
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.documents import seed_quote_template, sp_block
from smart_power.sp_quotes.quote_print import print_lines, quote_print
from smart_power.sp_sales.quotation import new_option
from smart_power.tests.test_print_template import chromium_works
from smart_power.tests.utils import load_erpnext_test_data, make_quotation

load_erpnext_test_data()

FORMAT = "SP Quotation"
COST_WORDS = ("sp_cost", "sp_total_cost", "sp_profit", "sp_margin", "sp_line_profit", "valuation", "markup")


def render(doc, as_pdf=False):
	return frappe.get_print("Quotation", doc.name, FORMAT, doc=doc, as_pdf=as_pdf, letterhead="Smart Power")


class TestQuotePrint(IntegrationTestCase):
	def setUp(self):
		# CI skips building assets; the print view looks bundles up in assets.json
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		seed_quote_template()
		self.a = make_quotation(save=False)
		self.a.append(
			"sp_optional_lines", {"item_code": "_Test Item", "rate": 9000, "note": "موتور استانلس كامل"}
		)
		self.a.insert()
		self.b = frappe.get_doc("Quotation", new_option(self.a.name))

	def test_two_options_side_by_side_rtl_with_total_in_words(self):
		html = render(self.a)
		self.assertTrue('dir="rtl"' in html)
		self.assertTrue(self.a.name in html and self.b.name in html, "both options are printed")
		self.assertTrue('class="sp-options-side"' in html)
		self.assertTrue(quote_print(self.a).totals.words in html, "the total in words")
		self.assertTrue("موتور استانلس كامل" in html, "the optional line under the total")
		self.assertTrue("sp-block-preamble" in html and "sp-block-warranty" in html, "the admin's text")
		self.assertFalse("{customer_name}" in html, "placeholders are filled")

	def test_one_option_prints_no_options_section(self):
		single = make_quotation()
		self.assertFalse('class="sp-options-side"' in render(single))

	def test_hidden_lines_are_left_out_and_merge_groups_print_as_one_line(self):
		rows = [
			frappe._dict(item_code="X1", item_name="لوح", qty=2, rate=100, amount=200),
			frappe._dict(
				item_code="X2", item_name="كابل", qty=1, rate=50, amount=50, sp_merge_group="أعمال كهربائية"
			),
			frappe._dict(
				item_code="X3", item_name="قاطع", qty=1, rate=30, amount=30, sp_merge_group="أعمال كهربائية"
			),
			frappe._dict(item_code="X4", item_name="عمولة", qty=1, rate=0, amount=0, sp_is_hidden=1),
		]
		lines = print_lines(rows, names={})
		self.assertEqual([line["description"] for line in lines], ["لوح", "أعمال كهربائية"])
		self.assertEqual((lines[1]["qty"], lines[1]["amount"], lines[1]["uom"]), (1, 80, "مقطوعية"))
		self.assertEqual([line["no"] for line in lines], [1, 2])

	def test_hidden_line_never_reaches_the_pdf(self):
		self.a.append("items", {"item_code": "_Test Item 2", "qty": 1, "rate": 777})
		self.a.items[-1].sp_is_hidden = 1  # SP-58's flag, set in memory here
		self.assertFalse("_Test Item 2" in render(self.a))

	def test_payment_schedule_prints_when_entered(self):
		self.a.reload()
		total = self.a.rounded_total or self.a.grand_total
		self.a.set(
			"payment_schedule",
			[
				{"due_date": self.a.transaction_date, "invoice_portion": 50, "payment_amount": total / 2},
				{"due_date": self.a.valid_till, "invoice_portion": 50, "payment_amount": total / 2},
			],
		)
		self.assertTrue("sp-quote-schedule" in render(self.a))

	def test_the_template_never_reads_a_cost(self):
		html = frappe.db.get_value("Print Format", FORMAT, "html")
		for word in COST_WORDS:
			self.assertNotIn(word, html)
		path = frappe.get_app_path("smart_power", "templates", "print", "quote_optional_lines.html")
		with open(path, encoding="utf-8") as f:
			partial = f.read()
		for word in COST_WORDS:
			self.assertNotIn(word, partial)

	def test_the_print_data_holds_no_cost(self):
		data = json.dumps(quote_print(self.a), default=str)
		for word in ("cost", "profit", "margin"):
			self.assertNotIn(word, data)

	def test_the_quote_print_format_is_the_one_sent(self):
		self.assertEqual(
			frappe.db.get_single_value("Smart Power Settings", "default_quote_print_format"), FORMAT
		)

	@unittest.skipUnless(chromium_works(), "Chromium cannot start here (missing system libraries)")
	def test_real_pdf(self):
		from pypdf import PdfReader

		pdf = PdfReader(io.BytesIO(render(self.a, as_pdf=True)))
		text = "".join(page.extract_text() for page in pdf.pages)
		self.assertIn(self.a.name, text)
		self.assertIn(self.b.name, text)

	def test_found_in_the_browser_check(self):
		# a new quote carries the Smart Power letterhead, units are not translated as "no",
		# amounts stay left to right in the admin's text, and optional lines use Arabic names
		from smart_power.sp_core.setup.print_setup import LETTER_HEAD, setup_printing

		setup_printing()
		self.assertEqual(make_quotation().letter_head, LETTER_HEAD)
		frappe.local.lang = "ar"
		try:
			self.assertEqual(frappe._("Nos"), "عدد")
		finally:
			frappe.local.lang = "en"
		preamble = str(sp_block("Quotation", "preamble", self.a))
		self.assertIn('<span class="sp-num">', preamble)
		frappe.db.set_value("Item", "_Test Item", "sp_name_ar", "صنف اختبار")
		self.assertEqual(quote_print(self.a).optional[0]["description"], "صنف اختبار")
