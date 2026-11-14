"""The base print template, letterhead and PDF settings (SP-23)."""

import base64
import io
import os
import subprocess
import unittest

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.printing import embed_image
from smart_power.sp_core.setup.print_setup import LETTER_HEAD, setup_printing

SAMPLE = "SP Print Sample"
SETTINGS = "SP Company Settings"


def chromium_works() -> bool:
	"""Chrome PDFs need Chromium and its system libraries (libnss3, libnspr4, libasound2)."""
	path = os.path.join(frappe.utils.get_bench_path(), "chromium", "chrome-linux", "headless_shell")
	path = frappe.get_common_site_config().get("chromium_path") or path
	if not os.access(path, os.X_OK):
		return False
	try:
		return subprocess.run([path, "--version"], capture_output=True, timeout=30).returncode == 0
	except OSError, subprocess.TimeoutExpired:
		return False


def sample(rows: int | None = None, as_pdf: bool = False):
	doc = frappe.get_doc(SETTINGS)
	if rows:
		doc.sample_rows = rows
	return frappe.get_print(SETTINGS, SETTINGS, SAMPLE, doc=doc, as_pdf=as_pdf, letterhead=LETTER_HEAD)


class TestPrintTemplate(IntegrationTestCase):
	def setUp(self):
		setup_printing()

	def test_print_settings(self):
		ps = frappe.get_single("Print Settings")
		self.assertEqual((ps.pdf_generator, ps.pdf_page_size, ps.repeat_header_footer), ("chrome", "A4", 1))

	def test_letterhead_is_the_default_over_erpnext_stock_ones(self):
		stock = (
			frappe.get_doc(
				{
					"doctype": "Letter Head",
					"letter_head_name": "Company Letterhead",
					"source": "HTML",
					"content": "<p>x</p>",
				}
			)
			if not frappe.db.exists("Letter Head", "Company Letterhead")
			else frappe.get_doc("Letter Head", "Company Letterhead")
		)
		if stock.is_new():
			stock.insert()
		frappe.db.set_value("Letter Head", {"is_default": 1}, "is_default", 0)
		frappe.db.set_value("Letter Head", stock.name, "is_default", 1)
		setup_printing()
		self.assertEqual(frappe.db.get_value("Letter Head", {"is_default": 1}), LETTER_HEAD)

	def test_admin_choice_of_default_is_kept(self):
		own = frappe.get_doc(
			{
				"doctype": "Letter Head",
				"letter_head_name": "ورق المدير",
				"source": "HTML",
				"content": "<p>x</p>",
			}
		).insert()
		frappe.db.set_value("Letter Head", {"is_default": 1}, "is_default", 0)
		frappe.db.set_value("Letter Head", own.name, "is_default", 1)
		setup_printing()
		self.assertEqual(frappe.db.get_value("Letter Head", {"is_default": 1}), own.name)

	def test_sample_has_header_footer_and_page_numbers(self):
		html = sample()
		self.assertTrue('id="header-html"' in html, 'id="header-html"')
		self.assertTrue('id="footer-html"' in html, 'id="footer-html"')
		self.assertTrue('class="page"' in html, 'class="page"')
		self.assertTrue('class="topage"' in html, 'class="topage"')
		self.assertTrue('dir="rtl"' in html, 'dir="rtl"')
		self.assertTrue("IBM Plex Sans Arabic" in html, "IBM Plex Sans Arabic")
		self.assertTrue(
			"مائة خمسة وعشرون ألفاً وأربعمائة خمسون جنيهاً وخمسون قرشاً" in html,
			"مائة خمسة وعشرون ألفاً وأربعمائة خمسون جنيهاً وخمسون قرشاً",
		)
		self.assertTrue("INVT GD100" in html, "INVT GD100")

	def test_header_shows_the_legal_data(self):
		company = frappe.get_doc(SETTINGS)
		company.legal_name_ar = "سمارت باور لأنظمة الطاقة"
		company.commercial_register = "123456"
		company.save()
		html = sample()
		self.assertTrue("سمارت باور لأنظمة الطاقة" in html, "سمارت باور لأنظمة الطاقة")
		self.assertTrue("123456" in html, "123456")

	def test_logo_is_embedded(self):
		self.assertTrue(
			embed_image("/assets/smart_power/images/sp_logo.png").startswith("data:image/png;base64,")
		)
		self.assertEqual(embed_image("https://example.com/x.png"), "https://example.com/x.png")

	def test_uploaded_logo_is_embedded_and_paths_cannot_escape(self):
		png = base64.b64decode(
			"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
		)
		logo = frappe.get_doc(
			{"doctype": "File", "file_name": "sp_test_logo.png", "content": png, "is_private": 0}
		).insert()
		self.assertTrue(embed_image(logo.file_url).startswith("data:image/png;base64,"))
		escape = "/assets/smart_power/../../../../sites/x.png"
		self.assertEqual(embed_image(escape), escape)

	@unittest.skipUnless(chromium_works(), "Chromium cannot start here (missing system libraries)")
	def test_pdf_repeats_the_header_and_numbers_the_pages(self):
		from pypdf import PdfReader

		company = frappe.get_doc(SETTINGS)
		company.legal_name_ar = "سمارت باور"
		company.save()
		reader = PdfReader(io.BytesIO(sample(rows=90, as_pdf=True)))
		pages = len(reader.pages)
		self.assertGreaterEqual(pages, 3)
		for number, page in enumerate(reader.pages, start=1):
			text = page.extract_text()
			self.assertIn("سمارت باور", text, number)  # the header on every page
			self.assertIn(f"{number}", text)
			self.assertIn(f"{pages}", text)
		first = reader.pages[0].extract_text()
		self.assertIn("INVT GD100", first)  # English stays left to right inside Arabic
