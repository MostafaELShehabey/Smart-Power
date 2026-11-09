"""Supplier master fields (SP-31)."""

import frappe
from frappe.tests import IntegrationTestCase


class TestSupplierFields(IntegrationTestCase):
	def test_fields_are_developer_owned(self):
		for fieldname in ("sp_is_consignment_owner", "sp_whatsapp", "sp_terms_note"):
			self.assertEqual(
				frappe.db.get_value("Custom Field", f"Supplier-{fieldname}", "module"), "SP Stock"
			)

	def test_consignment_owner_supplier(self):
		doc = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": "أفريقيا سيستم تجربة",
				"sp_is_consignment_owner": 1,
				"sp_whatsapp": "01001112222",
				"sp_terms_note": "50% مقدم والباقي عند الاستلام",
			}
		).insert()
		self.assertTrue(frappe.db.get_value("Supplier", doc.name, "sp_is_consignment_owner"))
		self.assertIn(doc.name, frappe.get_all("Supplier", {"sp_is_consignment_owner": 1}, pluck="name"))
