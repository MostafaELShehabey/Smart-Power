"""Bank quote formats (SP-171): the admin's own layouts in the new print format builder, the total
in Arabic words, a sent quote that keeps its PDF when the format changes later, and the classic
layouts of an older site moved to the new builder with the admin's changes."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.constants import ADMIN_MODULE
from smart_power.sp_core.documents import seed_quote_template
from smart_power.sp_core.printing import ar_date
from smart_power.sp_quotes import bank_formats as bf
from smart_power.sp_quotes.quote_send import send_quote
from smart_power.tests.test_quote_send import blank_pdf
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, set_setting

load_erpnext_test_data()

RATE = 450000
OLD_AL_AHLY, OLD_AGRI_BANK = "عرض سعر قديم - البنك الأهلي", "عرض سعر قديم - البنك الزراعي"


def classic_layouts() -> dict:
	"""The classic Print Format Builder layouts as SP-171 first seeded them, which a site
	installed before the move still holds."""

	def html(options):
		return {
			"fieldname": "_custom_html",
			"fieldtype": "HTML",
			"label": "Custom HTML",
			"print_hide": 0,
			"options": options,
		}

	def field(fieldname):
		return {"fieldname": fieldname, "label": bf.FIELDS[fieldname][0], "print_hide": 0}

	def section(label=""):
		return [{"fieldtype": "Section Break", "label": label}, {"fieldtype": "Column Break"}]

	def heading(title):
		return {
			"fieldname": "print_heading_template",
			"fieldtype": "Custom HTML",
			"options": bf.HEADING.format(title=title),
		}

	column = {"fieldtype": "Column Break"}
	payment = (
		"<div class='sp-bank-box'><b>طريقة الدفع : تحويلات بنكية</b><br>"
		"على أن يتم الدفع على حساب الشركة ببنك ……… رقم الحساب : ………</div>"
	)
	return {
		OLD_AL_AHLY: [
			heading("عرض سعر توريد وتركيب شبكات ري حديثة + محطة طاقة شمسية"),
			*section("بيانات العميل"),
			field("customer_name"),
			column,
			field("sp_customer_mobile"),
			*section("بيانات المحطة"),
			field("sp_site"),
			column,
			field("sp_water_source"),
			*section(),
			html("{{ bank_quote_table(doc, 'الإجمالي ( طاقة شمسية + شبكات ري )') }}"),
			field("sp_total_in_words"),
			html(bf.NOTE),
			*section(),
			html("<div class='sp-bank-box'><b>طريقة الدفع</b><br>تحويلات بنكية</div>"),
			field("valid_till"),
			field("sp_origin"),
			column,
			field("sp_warranty"),
			field("sp_execution_period"),
			field("sp_manufacture_year"),
			*section(),
			column,
			html(bf.SIGNATURE),
		],
		OLD_AGRI_BANK: [
			heading(
				"عرض سعر توريد وتركيب محطة طاقة شمسية شاملة الموتور والطلمبة ومشتملات تشغيل البئر"
			),
			*section("بيانات العميل"),
			field("customer_name"),
			column,
			field("sp_customer_mobile"),
			*section("بيانات المحطة"),
			field("sp_site"),
			column,
			field("sp_water_source"),
			*section(),
			html("{{ bank_quote_table(doc, 'الإجمالي ( طاقة شمسية + غاطس )') }}"),
			field("sp_total_in_words"),
			html(bf.NOTE),
			*section(),
			html(payment),
			field("valid_till"),
			field("sp_execution_period"),
			*section(),
			field("sp_origin"),
			column,
			field("sp_manufacture_year"),
			column,
			field("sp_warranty"),
			*section(),
			column,
			html(bf.SIGNATURE),
		],
	}


def make_classic(name: str, layout: list, css: str = bf.CSS):
	"""A classic builder format, as SP-171's seed inserted it."""
	return frappe.get_doc(
		{
			"doctype": "Print Format",
			"name": name,
			"doc_type": "Quotation",
			"module": ADMIN_MODULE,
			"standard": "No",
			"custom_format": 0,
			"print_format_builder": 1,
			"print_format_type": "Jinja",
			"default_print_language": "ar",
			"pdf_generator": "chrome",
			"show_section_headings": 1,
			"line_breaks": 0,
			"format_data": json.dumps(layout, ensure_ascii=False),
			"css": css,
		}
	).insert(ignore_permissions=True)


class TestBankFormats(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		bf.seed_bank_formats()

	def setUp(self):
		if frappe.utils.get_assets_json() is None:  # CI builds no assets
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		seed_quote_template()
		set_setting(followup_delay_days=2, default_quote_print_format="SP Quotation")

	def quote(self, **values):
		doc = make_quotation(rate=RATE, save=False)
		doc.update(values)
		return doc.insert()

	def classic(self, name, layout, css=bf.CSS):
		"""An older site's format; gone again after the test (the class shares one transaction)."""
		self.addCleanup(frappe.delete_doc, "Print Format", name, force=True)
		return make_classic(name, layout, css)

	def html(self, doc, print_format=bf.AL_AHLY):
		return frappe.get_print("Quotation", doc.name, print_format, doc=doc)

	def test_both_banks_get_a_format_the_admin_owns(self):
		for name in (bf.AL_AHLY, bf.AGRI_BANK):
			fmt = frappe.get_doc("Print Format", name)
			self.assertEqual(
				(fmt.doc_type, fmt.standard, fmt.module),
				("Quotation", "No", ADMIN_MODULE),
			)
			# a layout of the new builder: the classic one goes away in Frappe 17
			self.assertEqual((fmt.print_format_builder, fmt.print_format_builder_beta), (0, 1))
		fmt = frappe.get_doc("Print Format", bf.AL_AHLY)
		fmt.css += "\n.x { color: red; }"
		fmt.save()  # the admin edits it, with no developer mode
		self.assertEqual(bf.seed_bank_formats(), [])  # and a migrate never overwrites it

	def test_the_al_ahly_format_prints_the_sheets_facts_and_the_total_in_words(self):
		doc = self.quote(sp_water_source="آبار مياه جوفية", sp_origin="الصين", sp_manufacture_year="2025")
		self.assertEqual(doc.sp_total_in_words, "فقط أربعمائة وخمسون ألف جنيه لا غير")
		html = self.html(doc)
		for text in ("آبار مياه جوفية", "الصين", "2025", "سنة الصنع", doc.sp_total_in_words, "450,000"):
			self.assertIn(text, html)
		self.assertIn(f"التاريخ : {ar_date(doc.transaction_date)}", html)  # Jinja in the heading
		self.assertNotIn("{ ar_date", html)
		self.assertIn("sp-bank-table", html)  # and in the lines block
		self.assertNotIn("bank_quote_table(", html)
		# the sheet keeps its look in the new builder: grey heading bars, label beside value
		self.assertIn('<div class="section-label">بيانات العميل</div>', html)
		self.assertIn("field left-right", html)
		self.assertIn(bf.NEW_BUILDER_MARK, html)

	def test_a_field_dragged_onto_the_format_prints_with_no_code_change(self):
		doc = self.quote(order_type="Maintenance")
		self.assertNotIn("Maintenance", self.html(doc))
		fmt = frappe.get_doc("Print Format", bf.AL_AHLY)
		layout = json.loads(fmt.format_data)
		layout["sections"][0]["columns"][0]["fields"].append(
			{"fieldname": "order_type", "fieldtype": "Select", "label": "المساحة بالفدان"}
		)
		fmt.format_data = json.dumps(layout, ensure_ascii=False)
		fmt.save()
		frappe.clear_cache(doctype="Quotation")
		html = self.html(frappe.get_doc("Quotation", doc.name))
		self.assertIn("المساحة بالفدان", html)

	def test_a_hidden_line_never_reaches_the_bank(self):
		doc = make_quotation(rate=RATE, save=False)
		doc.append("items", {"item_code": "_Test Item", "qty": 1, "rate": 777})
		doc.insert()
		doc.items[-1].sp_is_hidden = 1  # SP-58's flag, set in memory (as in test_quote_print)
		table = str(bf.bank_quote_table(doc))
		self.assertNotIn("<td class='sp-n'>777</td>", table)  # its row is not printed
		self.assertIn("450,777", table)  # but its price is in the total, as on the customer PDF

	def test_a_quote_sent_before_the_bank_changed_its_format_keeps_its_pdf(self):
		doc = self.quote()
		with patch("frappe.get_print", return_value=blank_pdf()):
			result = send_quote(doc.name, print_format=bf.AGRI_BANK)
		log = frappe.get_doc("SP Quote Send Log", result["log"])
		self.assertEqual(log.print_format, bf.AGRI_BANK)
		before = frappe.get_doc("File", log.file).get_content()
		fmt = frappe.get_doc("Print Format", bf.AGRI_BANK)
		fmt.css += "\n.sp-bank-table th { background: #000; }"
		fmt.save()
		self.assertEqual(frappe.get_doc("File", log.file).get_content(), before)

	def test_the_classic_layouts_of_an_older_site_move_to_the_new_builder_as_a_fresh_seed(self):
		for name, layout in classic_layouts().items():
			self.classic(name, layout)
		self.assertEqual(sorted(bf.convert_to_new_builder()), sorted([OLD_AL_AHLY, OLD_AGRI_BANK]))
		look = ["font_size", "show_label_colon", "margin_top", "margin_bottom", "page_number", "pdf_generator"]
		for old, new in ((OLD_AL_AHLY, bf.AL_AHLY), (OLD_AGRI_BANK, bf.AGRI_BANK)):
			moved, seeded = frappe.get_doc("Print Format", old), frappe.get_doc("Print Format", new)
			self.assertEqual((moved.print_format_builder, moved.print_format_builder_beta), (0, 1))
			# the same layout, look and CSS a fresh install seeds
			self.assertEqual(json.loads(moved.format_data), bf.FORMATS[new]())
			self.assertEqual([moved.get(f) for f in look], [seeded.get(f) for f in look])
			self.assertEqual(moved.css, bf.CSS + bf.NEW_BUILDER_CSS)
			# Frappe keeps the classic layout, for its "Restore classic layout" button
			self.assertEqual(json.loads(moved.classic_format_data)["format_data"], classic_layouts()[old])
		self.assertEqual(bf.convert_to_new_builder(), [])  # once: a later migrate leaves them alone

	def test_what_the_admin_changed_in_a_classic_layout_survives_the_move(self):
		layout = classic_layouts()[OLD_AL_AHLY]
		layout.insert(4, {"fieldname": "order_type", "label": "المساحة بالفدان", "print_hide": 0})
		next(df for df in layout if df.get("fieldname") == "sp_origin")["label"] = "بلد الصنع"
		note = next(df for df in layout if "sp-bank-note" in (df.get("options") or ""))
		note["options"] = "<div class='sp-bank-note'>الأسعار سارية لمدة أسبوع</div>"
		self.classic(OLD_AL_AHLY, layout, css=bf.CSS + ".sp-bank-note { color: #00f; }\n")
		self.assertEqual(bf.convert_to_new_builder(only=["Standard"]), [])
		self.assertEqual(bf.convert_to_new_builder(only=[OLD_AL_AHLY]), [OLD_AL_AHLY])
		fmt = frappe.get_doc("Print Format", OLD_AL_AHLY)
		self.assertIn(".sp-bank-note { color: #00f; }", fmt.css)
		self.assertEqual(fmt.css.count(bf.NEW_BUILDER_MARK), 1)
		html = self.html(self.quote(order_type="Maintenance", sp_origin="الصين"), OLD_AL_AHLY)
		for text in ("المساحة بالفدان", "بلد الصنع", "الأسعار سارية لمدة أسبوع", "field left-right"):
			self.assertIn(text, html)
		self.assertNotIn("بلد المنشأ", html)

	def test_a_format_that_is_not_the_banks_sheet_is_left_alone(self):
		self.classic(OLD_AL_AHLY, classic_layouts()[OLD_AL_AHLY], css=".x { color: red; }")
		self.assertEqual(bf.convert_to_new_builder(), [])
		self.assertEqual(frappe.db.get_value("Print Format", OLD_AL_AHLY, "print_format_builder"), 1)
