"""Bank quote formats (SP-171): the admin's own layouts, the total in Arabic words, and a sent
quote that keeps its PDF when the format changes later."""

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

	def html(self, doc, print_format=bf.AL_AHLY):
		return frappe.get_print("Quotation", doc.name, print_format, doc=doc)

	def test_both_banks_get_a_format_the_admin_owns(self):
		for name in (bf.AL_AHLY, bf.AGRI_BANK):
			fmt = frappe.get_doc("Print Format", name)
			self.assertEqual(
				(fmt.doc_type, fmt.standard, fmt.print_format_builder, fmt.module),
				("Quotation", "No", 1, ADMIN_MODULE),
			)
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

	def test_a_field_dragged_onto_the_format_prints_with_no_code_change(self):
		doc = self.quote(order_type="Maintenance")
		self.assertNotIn("Maintenance", self.html(doc))
		fmt = frappe.get_doc("Print Format", bf.AL_AHLY)
		layout = json.loads(fmt.format_data)
		layout.insert(4, {"fieldname": "order_type", "label": "المساحة بالفدان", "print_hide": 0})
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
