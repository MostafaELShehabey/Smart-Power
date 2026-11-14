"""Document templates (SP-134, X8): versions, placeholders and the blocks print formats use."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.documents import seed_quote_template, sp_block, sp_blocks
from smart_power.tests.utils import load_erpnext_test_data, make_quotation

load_erpnext_test_data()

TEMPLATE = "SP Document Template"


def quote_template():
	seed_quote_template()
	return frappe.get_doc(
		TEMPLATE, frappe.db.get_value(TEMPLATE, {"document": "Quotation", "is_published": 1})
	)


def new_template(document="Invoice", blocks=None):
	return frappe.get_doc(
		{
			"doctype": TEMPLATE,
			"document": document,
			"blocks": blocks or [{"block_key": "intro", "title": "مقدمة", "body": "<p>{customer_name}</p>"}],
		}
	).insert()


class TestDocumentTemplates(IntegrationTestCase):
	def test_a_first_quote_template_is_published(self):
		template = quote_template()
		self.assertEqual(
			[b.block_key for b in template.blocks], ["preamble", "execution_period", "warranty", "terms"]
		)

	def test_misspelled_placeholder_is_refused_listing_the_valid_ones(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			new_template("Quotation", [{"block_key": "intro", "body": "<p>{custmer_name}</p>"}])
		message = str(ctx.exception)
		self.assertIn("{custmer_name}", message)
		self.assertIn("{customer_name}", message)  # the valid ones are listed

	def test_a_placeholder_of_another_document_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			new_template("Purchase Order", [{"block_key": "intro", "body": "<p>{valid_till}</p>"}])

	def test_published_warranty_change_shows_on_new_prints(self):
		quote = make_quotation()
		v1 = quote_template()
		self.assertIn("الشركة المصنعة", str(sp_block("Quotation", "warranty", quote)))
		v2 = frappe.get_doc(TEMPLATE, v1.new_version())
		next(b for b in v2.blocks if b.block_key == "warranty").body = "<p>ضمان خمس سنوات على الألواح.</p>"
		v2.save()
		self.assertNotIn("خمس سنوات", str(sp_block("Quotation", "warranty", quote)))  # still a draft
		v2.publish()
		self.assertIn("خمس سنوات", str(sp_block("Quotation", "warranty", quote)))
		self.assertFalse(frappe.db.get_value(TEMPLATE, v1.name, "is_published"))

	def test_published_version_is_frozen(self):
		template = quote_template()
		template.blocks[0].body = "<p>تغيير</p>"
		with self.assertRaises(frappe.ValidationError):
			template.save()

	def test_placeholders_are_filled_from_the_quote(self):
		quote = make_quotation()
		html = str(sp_block("Quotation", "preamble", quote))
		self.assertIn(quote.name, html)
		self.assertIn(quote.customer_name or quote.party_name, html)
		self.assertNotIn("{", html)
		self.assertEqual(len(sp_blocks("Quotation", quote)), 4)

	def test_text_is_never_run_as_code_and_values_are_escaped(self):
		template = new_template(blocks=[{"block_key": "intro", "body": "<p>{{ 7 * 7 }} {customer_name}</p>"}])
		template.publish()
		html = str(sp_block("Invoice", "intro", frappe._dict(customer_name="<b>x</b>")))
		self.assertIn("{{ 7 * 7 }}", html)
		self.assertNotIn("49", html)
		self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)

	def test_block_keys(self):
		for key in ("Intro", "2nd", "with space"):
			with self.assertRaises(frappe.ValidationError, msg=key):
				new_template(blocks=[{"block_key": key, "body": "x"}])
		with self.assertRaises(frappe.ValidationError):
			new_template(blocks=[{"block_key": "a", "body": "x"}, {"block_key": "a", "body": "y"}])

	def test_missing_block_or_document_prints_nothing(self):
		self.assertEqual(str(sp_block("Quotation", "no_such_block", None)), "")
		self.assertEqual(sp_blocks("Customer Statement", None), [])

	def test_preview_fills_from_a_quote(self):
		quote = make_quotation()
		blocks = quote_template().preview(quote.name)
		self.assertIn(quote.name, blocks[0])

	def test_publish_works_the_way_the_form_calls_it(self):
		# found in the browser check: the Publish button sent an empty "check" argument, which
		# Frappe's argument validation refused; publish now takes no arguments
		import inspect

		from smart_power.sp_core.doctype.sp_document_template.sp_document_template import SPDocumentTemplate

		self.assertEqual(list(inspect.signature(SPDocumentTemplate.publish).parameters), ["self"])
		draft = new_template()
		draft.run_method("publish")
		self.assertTrue(frappe.db.get_value(TEMPLATE, draft.name, "is_published"))
