"""Values in use cannot be deleted (SP-32)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.tests.test_lists import DT, make


class TestDeleteGuard(IntegrationTestCase):
	def test_value_in_use_cannot_be_deleted(self):
		parent = make(code="PARENT_A")
		make(code="CHILD_A", parent_value=parent.name)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc(DT, parent.name)
		self.assertTrue(frappe.db.exists(DT, parent.name))

	def test_unused_value_can_be_deleted(self):
		doc = make(code="UNUSED")
		frappe.delete_doc(DT, doc.name)
		self.assertFalse(frappe.db.exists(DT, doc.name))

	def test_value_cannot_be_its_own_parent(self):
		doc = make(code="SELF")
		doc.parent_value = doc.name
		with self.assertRaises(frappe.ValidationError):
			doc.save()
