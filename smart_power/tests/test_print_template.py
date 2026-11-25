"""The base print template, the brand letterhead and PDF settings (SP-23, SP-185)."""

import base64
import html
import io
import os
import subprocess
import unittest
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core import letterhead
from smart_power.sp_core.printing import embed_image
from smart_power.sp_core.setup.print_setup import (
	BRAND_LETTER_HEAD,
	LETTER_HEAD,
	_template,
	adopt_brand_letter_head,
	setup_printing,
)

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


MISSING_LOGO = "/files/sp-gone-logo.png"


def missing_logo() -> str:
	"""A File record whose file is not on disk (an admin's logo deleted from the server)."""
	if not frappe.db.exists("File", {"file_url": MISSING_LOGO}):
		frappe.get_doc(
			{"doctype": "File", "file_name": "sp-gone-logo.png", "file_url": MISSING_LOGO, "is_private": 0}
		).db_insert()
	return MISSING_LOGO


def sample(rows: int | None = None, as_pdf: bool = False):
	doc = frappe.get_doc(SETTINGS)
	if rows:
		doc.sample_rows = rows
	try:
		return frappe.get_print(SETTINGS, SETTINGS, SAMPLE, doc=doc, as_pdf=as_pdf, letterhead=LETTER_HEAD)
	except Exception as e:
		# Frappe wraps a template error's traceback in HTML: show the real cause
		raise AssertionError(html.unescape(str(e))[-4000:]) from None


class TestPrintTemplate(IntegrationTestCase):
	def setUp(self):
		setup_printing()
		# the tests of a class share one transaction: each starts from the app's own letterhead
		frappe.db.set_value(
			"Letter Head",
			LETTER_HEAD,
			{"content": _template("letterhead_header.html"), "footer": _template("letterhead_footer.html")},
		)
		frappe.db.delete("Letter Head", {"name": BRAND_LETTER_HEAD})
		# CI skips building assets, so there is no assets.json and Frappe's print view fails
		# looking up print.bundle.css; a real bench always has one. Plain paths are fine here.
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)

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
		# and the site's default, which ERPNext copies onto new quotes (found in the SP-62 check)
		self.assertEqual(frappe.db.get_default("letter_head"), LETTER_HEAD)

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
			"مائة وخمسة وعشرون ألفاً وأربعمائة وخمسون جنيهاً وخمسون قرشاً" in html,
			"مائة وخمسة وعشرون ألفاً وأربعمائة وخمسون جنيهاً وخمسون قرشاً",
		)
		self.assertTrue("INVT GD100" in html, "INVT GD100")

	def test_header_shows_the_brand_and_no_legal_lines(self):
		company = frappe.get_doc(SETTINGS)
		company.logo = missing_logo()  # a logo whose file is gone from disk still prints
		company.legal_name_ar = "سمارت باور لأنظمة الطاقة"
		company.commercial_register = "123456"
		company.brand_name_en, company.brand_name_ar = "Smart Power", "سمارت باور"
		company.tagline_ar = "لأنظمة الطاقة الشمسية والري"
		company.save()
		html = sample()
		self.assertIn("سمارت باور", html)
		self.assertIn("لأنظمة الطاقة الشمسية والري", html)  # the admin's tagline, not the default
		# the owner's decision (2026-11-25): the commercial register and tax card print nowhere
		self.assertNotIn("123456", html)
		self.assertNotIn("سمارت باور لأنظمة الطاقة<", html)

	def test_brand_names_fall_back_to_the_defaults(self):
		company = frappe.get_doc(SETTINGS)
		company.brand_name_en = company.brand_name_ar = company.tagline_ar = None
		company.save()
		data = letterhead.letterhead()
		self.assertEqual(
			(data["name_en"], data["name_ar"], data["tagline"]),
			(letterhead.BRAND_EN, letterhead.BRAND_AR, letterhead.TAGLINE_AR),
		)

	def test_footer_shows_the_contacts_of_company_settings(self):
		company = frappe.get_doc(SETTINGS)
		company.email = "office@smartpower.test"
		company.set("addresses", [])
		company.append("addresses", {"label": "الإدارة", "address_ar": "الخارجة", "phone": "01000000001"})
		company.append("addresses", {"label": "المعرض", "address_ar": "المنيرة", "phone": "01000000002"})
		company.append("addresses", {"label": "المخزن", "address_ar": "الخارجة 2", "phone": "01000000001"})
		company.save()
		html = sample()
		for text in (
			"01000000001",
			"01000000002",
			"office@smartpower.test",
			"الإدارة: الخارجة",
			"المعرض: المنيرة",
		):
			self.assertIn(text, html)
		self.assertEqual(html.count("01000000001"), 1)  # a phone two addresses share prints once
		# the admin changes a phone: the next print shows it
		company.addresses[1].phone = "01000000009"
		company.save()
		html = sample()
		self.assertIn("01000000009", html)
		self.assertNotIn("01000000002", html)

	def test_letterhead_carries_its_own_look(self):
		# found in the SP-62 check: under ERPNext's own print formats the logo filled the page
		content, footer = frappe.db.get_value("Letter Head", LETTER_HEAD, ["content", "footer"])
		for part in (content, footer):
			self.assertIn("sp-lh-style", part)
			self.assertIn("viewBox", part)
		self.assertIn("letterhead()", content)

	def test_prints_carry_the_brand_colours_only(self):
		"""No gold or old navy left in what the app prints."""
		import glob

		app = frappe.get_app_path("smart_power")
		files = [
			os.path.join(app, "public", "css", "sp_print.css"),
			*glob.glob(os.path.join(app, "templates", "print", "*.html")),
			*glob.glob(os.path.join(app, "*", "print_format", "*", "*.json")),
		]
		self.assertGreater(len(files), 10)  # sp-allow-number: the stylesheet, the templates and the formats
		for path in files:
			text = frappe.read_file(path).lower()
			self.assertNotIn("#c8a24a", text, path)
			self.assertNotIn("#0b2e59", text, path)

	def test_app_made_letterhead_gets_the_brand_design(self):
		old_header, old_footer = "<div>SP-62 header</div>", "<div>SP-23 footer</div>"
		frappe.db.set_value("Letter Head", LETTER_HEAD, {"content": old_header, "footer": old_footer})
		self.assertEqual(adopt_brand_letter_head(headers=(old_header,), footers=(old_footer,)), LETTER_HEAD)
		self.assertIn("sp-lh-head", frappe.db.get_value("Letter Head", LETTER_HEAD, "content"))
		self.assertIn("sp-lh-foot", frappe.db.get_value("Letter Head", LETTER_HEAD, "footer"))
		self.assertFalse(frappe.db.exists("Letter Head", BRAND_LETTER_HEAD))

	def test_edited_letterhead_is_kept_and_stays_the_default(self):
		edited = "<div>the admin's own header</div>"
		frappe.db.set_value("Letter Head", LETTER_HEAD, "content", edited)
		default = frappe.db.get_value("Letter Head", {"is_default": 1})
		got = adopt_brand_letter_head(
			headers=("<div>SP-62 header</div>",), footers=("<div>SP-23 footer</div>",)
		)
		self.assertEqual(got, BRAND_LETTER_HEAD)
		self.assertEqual(frappe.db.get_value("Letter Head", LETTER_HEAD, "content"), edited)
		self.assertEqual(frappe.db.get_value("Letter Head", {"is_default": 1}), default)
		# the brand design waits beside it for the admin to choose
		self.assertIn("sp-lh-head", frappe.db.get_value("Letter Head", BRAND_LETTER_HEAD, "content"))
		self.assertFalse(frappe.db.get_value("Letter Head", BRAND_LETTER_HEAD, "is_default"))

	def test_pdf_with_our_letterhead_goes_edge_to_edge(self):
		from bs4 import BeautifulSoup

		html = (
			"<html><head><style>.print-format { margin-left: 10mm; }</style></head><body>"
			'<div id="header-html"><div class="letter-head"><div class="sp-lh"></div></div><h2>Heading</h2></div>'
			'<div class="print-format">body</div>'
			'<div id="footer-html"><div class="letter-head-footer"><div class="sp-lh">'
			'<svg><text class="sp-lh-pageno"><tspan class="page"></tspan></text></svg></div></div>'
			'<p class="page-number"><span class="page"></span> of <span class="topage"></span></p></div>'
			"</body></html>"
		)
		soup = BeautifulSoup(html, "html.parser")
		for html_id in ("header-html", "footer-html"):
			content = soup.find(id=html_id)
			page = letterhead.pdf_header_html(
				soup, soup.head.contents, content, soup.find_all("style"), html_id, []
			)
			# what the format prints beside the letterhead keeps the side margins
			self.assertIn("padding-left: 10mm; padding-right: 15mm", page)
		from frappe.utils.pdf import get_print_format_styles

		margins = {rule.name: rule.value for rule in get_print_format_styles(soup)}
		self.assertEqual(
			[margins[side] for side in ("margin-left", "margin-right", "margin-top", "margin-bottom")],
			["0", "0", "0", "0"],
		)
		# the body gets its side margins back as padding, once
		self.assertEqual(len(soup.find_all("style", id=letterhead.PAGE_STYLE_ID)), 1)
		self.assertIn("padding-left: 10mm !important", soup.find("style", id=letterhead.PAGE_STYLE_ID).string)
		# our footer numbers the pages: the format's own page line is dropped
		self.assertFalse(soup.find(class_="page-number"))
		self.assertTrue(soup.find(class_="sp-lh-pageno").find(class_="page"))

	def test_pdf_of_a_builder_layout_goes_edge_to_edge(self):
		from bs4 import BeautifulSoup

		html = (
			"<html><head><style>@page { size: A4 portrait; margin-top: 10mm; margin-left: 8mm; margin-right: 8mm; "
			"@bottom-center { content: counter(page) } } body { max-width: 194mm !important; }</style></head>"
			'<body class="print-format-doc"><div id="header-html"><div class="letter-head">'
			'<div class="sp-lh"></div></div></div>body</body></html>'
		)
		soup = BeautifulSoup(html, "html.parser")
		letterhead.pdf_header_html(
			soup, soup.head.contents, soup.find(id="header-html"), [], "header-html", []
		)
		rule = soup.head.style.string
		self.assertIn("margin-top: 0;", rule)
		self.assertIn("margin-left: 0;", rule)
		self.assertIn("margin-right: 0;", rule)
		self.assertIn("@bottom-center { content: counter(page) }", rule)  # the rest of the rule is kept
		own = soup.find("style", id=letterhead.PAGE_STYLE_ID).string
		self.assertIn("body.print-format-doc", own)
		self.assertIn("padding-left: 8mm !important", own)
		self.assertIn("max-width: none !important", own)

	def test_another_letterhead_is_left_alone(self):
		from bs4 import BeautifulSoup

		soup = BeautifulSoup(
			'<html><head></head><body><div id="header-html"><div class="letter-head">other</div></div></body></html>',
			"html.parser",
		)
		letterhead.pdf_header_html(
			soup, soup.head.contents, soup.find(id="header-html"), [], "header-html", []
		)
		self.assertFalse(soup.find("style", id=letterhead.PAGE_STYLE_ID))

	def test_logo_is_embedded(self):
		self.assertTrue(
			embed_image("/assets/smart_power/images/sp_logo.png").startswith("data:image/png;base64,")
		)
		# the company's stacked logo, as on its letterhead: what prints until the admin uploads one
		frappe.db.set_single_value(SETTINGS, "logo", None)
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		self.assertTrue(letterhead.company_logo().endswith("sp_logo_stacked.png"))
		self.assertTrue(letterhead.letterhead()["logo"].startswith("data:image/png;base64,"))
		self.assertEqual(embed_image("https://example.com/x.png"), "https://example.com/x.png")

	def test_uploaded_logo_is_embedded_and_paths_cannot_escape(self):
		png = base64.b64decode(
			"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
		)
		logo = frappe.get_doc(
			{"doctype": "File", "file_name": "sp_test_logo.png", "content": png, "is_private": 0}
		).insert()
		self.assertTrue(embed_image(logo.file_url).startswith("data:image/png;base64,"))
		# a File record whose file is gone from disk never breaks a print
		missing = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "gone.png",
				"file_url": "/files/sp-gone-logo.png",
				"is_private": 0,
			}
		)
		missing.db_insert()
		self.assertEqual(embed_image("/files/sp-gone-logo.png"), "/files/sp-gone-logo.png")
		escape = "/assets/smart_power/../../../../sites/x.png"
		self.assertEqual(embed_image(escape), escape)

	@unittest.skipUnless(chromium_works(), "Chromium cannot start here (missing system libraries)")
	def test_pdf_repeats_the_header_and_numbers_the_pages(self):
		from pypdf import PdfReader

		company = frappe.get_doc(SETTINGS)
		company.brand_name_en = "Smart Power"
		company.email = "office@smartpower.test"
		company.set("addresses", [])
		company.append("addresses", {"label": "الإدارة", "address_ar": "الخارجة", "phone": "01000000001"})
		company.save()
		reader = PdfReader(io.BytesIO(sample(rows=90, as_pdf=True)))
		pages = len(reader.pages)
		self.assertGreaterEqual(pages, 3)
		for number, page in enumerate(reader.pages, start=1):
			# Arabic comes out of a PDF as joined letter shapes, so the header is checked by its
			# English name and the footer by its phone and email, on every page
			text = page.extract_text()
			self.assertIn("Smart Power", text, number)
			self.assertIn("01000000001", text, number)
			self.assertIn("office@smartpower.test", text, number)
			self.assertIn(f"{number}", text)
			self.assertIn(f"{pages}", text)
		self.assertIn("INVT GD100", reader.pages[0].extract_text())  # English stays left to right
