"""Arabic and Egyptian defaults (SP-22)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.formatting import datetime_12h, time_12h
from smart_power.sp_core.setup.locale import BRAND_HTML, LOGO, apply_branding, apply_locale


class TestLocale(IntegrationTestCase):
	def test_apply_locale(self):
		apply_locale()
		ss = frappe.get_single("System Settings")
		self.assertEqual(
			(ss.language, ss.country, ss.time_zone, ss.date_format, ss.currency, ss.first_day_of_the_week),
			("ar", "Egypt", "Africa/Cairo", "dd-mm-yyyy", "EGP", "Saturday"),
		)
		self.assertEqual(frappe.db.get_default("currency"), "EGP")
		self.assertTrue(frappe.db.exists("Fiscal Year", {"year_start_date": "2027-01-01"}))

	def test_money_reads_like_the_spec(self):
		apply_locale()
		self.assertEqual(
			frappe.db.get_value("Currency", "EGP", ["symbol", "symbol_on_right", "number_format"]),
			("EGP", 1, "#,###.##"),
		)
		self.assertEqual(frappe.utils.fmt_money(12345, currency="EGP"), "12,345.00 EGP")

	def test_dates_read_dd_mm_yyyy(self):
		apply_locale()
		frappe.local.user_date_format = None
		self.assertEqual(frappe.utils.formatdate("2027-03-09"), "09-03-2027")

	def test_twelve_hour_clock(self):
		frappe.local.lang = "en"
		self.assertEqual(time_12h("09:05:00"), "09:05 AM")
		self.assertEqual(time_12h("21:30"), "09:30 PM")
		self.assertEqual(time_12h(None), "")

	def test_twelve_hour_clock_in_arabic(self):
		frappe.local.lang = "ar"
		try:
			self.assertEqual(time_12h("21:30"), "09:30 م")
			self.assertEqual(time_12h("00:15"), "12:15 ص")
		finally:
			frappe.local.lang = "en"

	def test_datetime_uses_site_date_format(self):
		apply_locale()
		frappe.local.user_date_format = None
		frappe.local.lang = "en"
		self.assertEqual(datetime_12h("2027-03-09 14:00:00"), "09-03-2027 02:00 PM")

	def test_branding(self):
		apply_branding()
		ws = frappe.get_single("Website Settings")
		self.assertEqual((ws.app_name, ws.app_logo, ws.brand_html), ("Smart Power", LOGO, BRAND_HTML))
		self.assertEqual(frappe.db.get_single_value("System Settings", "app_name"), "Smart Power")

	def test_every_report_and_page_has_an_arabic_title(self):
		"""BUG-20: the winch month grid and year summary showed their English names as titles."""
		from frappe.translate import get_all_translations

		arabic = get_all_translations("ar")
		modules = frappe.get_module_list("smart_power")
		titles = frappe.get_all("Report", {"module": ("in", modules), "is_standard": "Yes"}, pluck="name")
		titles += [
			p.title or p.name for p in frappe.get_all("Page", {"module": ("in", modules)}, ["name", "title"])
		]
		self.assertEqual([t for t in titles if t not in arabic], [])

	def test_hooks(self):
		self.assertIn(
			"smart_power.sp_core.setup.locale.apply_locale", frappe.get_hooks("setup_wizard_complete")
		)
		self.assertIn("/assets/smart_power/js/sp_locale.js", frappe.get_hooks("app_include_js"))
		methods = frappe.get_hooks("jinja")["methods"]
		self.assertIn("smart_power.sp_core.formatting.time_12h", methods)
