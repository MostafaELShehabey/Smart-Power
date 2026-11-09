"""Admin lists, X4 (SP-32)."""

import frappe
from frappe.tests import IntegrationTestCase

DT = "SP List Value"


def make(list_name="Region", code="TEST_A", value_ar="قيمة", **kw):
	return frappe.get_doc(
		{"doctype": DT, "list_name": list_name, "code": code, "value_ar": value_ar, **kw}
	).insert()


class TestListValueRecord(IntegrationTestCase):
	def test_named_by_list_and_clean_code(self):
		doc = make(code=" dakhla oasis ")
		self.assertEqual((doc.code, doc.name), ("DAKHLA_OASIS", "Region-DAKHLA_OASIS"))

	def test_list_and_code_are_fixed_once_saved(self):
		doc = make(code="FIXED")
		doc.code = "OTHER"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_duplicate_code_in_the_same_list_is_refused(self):
		make(code="TWICE")
		with self.assertRaises(frappe.ValidationError):
			make(code="twice")
