"""Helpers for printed documents (SP-23): money, amounts in Arabic words, dates, QR, signatures."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.printing import ar_date, ar_words, money, number_words, qr, signature_block


class TestPrinting(IntegrationTestCase):
	def test_the_story_amount_in_words(self):
		self.assertEqual(
			ar_words(125450.50),
			"مائة وخمسة وعشرون ألفاً وأربعمائة وخمسون جنيهاً وخمسون قرشاً",
		)

	def test_counted_words_agree_with_the_number(self):
		cases = {
			1: "جنيه",
			2: "جنيهان",
			3: "ثلاثة جنيهات",
			10: "عشرة جنيهات",
			11: "أحد عشر جنيهاً",
			25: "خمسة وعشرون جنيهاً",
			100: "مائة جنيه",
			1000: "ألف جنيه",
			2000: "ألفا جنيه",
			3000: "ثلاثة آلاف جنيه",
			11000: "أحد عشر ألف جنيه",
			2500000: "مليونان وخمسمائة ألف جنيه",
			450000: "أربعمائة وخمسون ألف جنيه",  # the Al-Ahly sheet's own words (SP-171)
			105: "مائة وخمسة جنيهات",
			311: "ثلاثمائة وأحد عشر جنيهاً",
			0: "صفر جنيه",
			0.5: "خمسون قرشاً",
			12.05: "اثنا عشر جنيهاً وخمسة قروش",
		}
		for value, words in cases.items():
			self.assertEqual(ar_words(value), words, value)

	def test_numbers_without_currency(self):
		self.assertEqual(number_words(125450), "مائة وخمسة وعشرون ألفاً وأربعمائة وخمسون")
		self.assertEqual(ar_words(17, with_currency=False), "سبعة عشر")

	def test_money_has_thousands_separators(self):
		self.assertIn("125,450.50", money(125450.5))

	def test_arabic_date(self):
		self.assertEqual(ar_date("2026-11-14"), "14 نوفمبر 2026")
		self.assertEqual(ar_date(None), "")

	def test_signature_block_escapes_labels(self):
		html = str(signature_block("المستلم", "<b>x</b>"))
		self.assertIn("المستلم", html)
		self.assertNotIn("<b>x</b>", html)

	def test_qr_is_an_image(self):
		self.assertIn('src="data:image/svg+xml;base64,', str(qr("https://example.com/r/1")))
		self.assertEqual(str(qr("")), "")

	def test_helpers_work_in_print_templates(self):
		html = frappe.render_template("{{ ar_words(1000) }} | {{ ar_date('2026-01-01') }}", {})
		self.assertEqual(html, "ألف جنيه | 1 يناير 2026")
