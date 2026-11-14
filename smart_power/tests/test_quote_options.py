"""Full alternative quotes A/B/C on one case (SP-59)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.quotation import approve_version, new_option, new_version
from smart_power.tests.utils import load_erpnext_test_data, make_quotation

load_erpnext_test_data()


def get(name):
	return frappe.get_doc("Quotation", name)


class TestQuoteOptions(IntegrationTestCase):
	def setUp(self):
		self.a = make_quotation()
		self.case = self.a.sp_case

	def test_first_quote_is_option_a(self):
		self.assertEqual(self.a.sp_option_label, "A")

	def test_new_option_takes_the_next_free_label(self):
		b = get(new_option(self.a.name))
		self.assertEqual((b.sp_option_label, b.sp_root, b.docstatus), ("B", b.name, 0))
		self.assertFalse(b.sp_previous_version)
		self.assertEqual(b.sp_version, self.a.sp_version + 1)  # versions count per case
		c = get(new_option(b.name))
		self.assertEqual(c.sp_option_label, "C")
		with self.assertRaises(frappe.ValidationError):
			new_option(c.name)

	def test_versions_of_an_option_keep_its_label(self):
		b = get(new_option(self.a.name))
		b2 = get(new_version(b.name))
		self.assertEqual((b2.sp_option_label, b2.sp_root), ("B", b.name))

	def test_two_alternatives_cannot_share_a_label(self):
		b = get(new_option(self.a.name))
		b.sp_option_label = "A"
		with self.assertRaises(frappe.ValidationError):
			b.save()

	def test_any_option_can_be_the_approved_version(self):
		b = get(new_option(self.a.name))
		self.a.submit()
		b.submit()
		approve_version(b.name)
		self.assertEqual(frappe.db.get_value("SP Case", self.case, "accepted_quotation"), b.name)
		self.assertEqual(get(b.name).sp_status, "Approved")
		# the customer changes their mind: A is approved and B is not any more
		approve_version(self.a.name)
		self.assertFalse(get(b.name).sp_is_approved)
		self.assertEqual(frappe.db.get_value("SP Case", self.case, "accepted_quotation"), self.a.name)

	def test_an_option_starts_from_the_quote_it_copies(self):
		self.a.append("sp_optional_lines", {"item_code": "_Test Item", "rate": 500, "note": "طلمبة ثانية"})
		self.a.save()
		b = get(new_option(self.a.name))
		self.assertEqual([r.note for r in b.sp_optional_lines], ["طلمبة ثانية"])
		self.assertEqual(b.grand_total, self.a.grand_total)
