"""The record pattern (SP-45): the owner chips and the status bar have what they read."""

import frappe
from frappe.tests import UnitTestCase

from smart_power import records


class TestRecordPattern(UnitTestCase):
	def test_owner_chips_are_owner_fields_with_a_history_kind(self):
		kinds = frappe.get_meta("SP Owner History").get_field("role_kind").options.split("\n")
		for doctype, owners in records.owner_fields().items():
			meta = frappe.get_meta(doctype)
			self.assertTrue(meta.get_field("owner_history"), doctype)
			for fieldname, kind in owners.items():
				field = meta.get_field(fieldname)
				self.assertEqual((field.fieldtype, field.options), ("Link", "User"), fieldname)
				self.assertIn(kind, kinds, fieldname)

	def test_boot_carries_the_owner_fields(self):
		bootinfo = frappe._dict()
		records.boot(bootinfo)
		self.assertEqual(
			list(bootinfo.sp_owner_fields["SP Station"]),
			["sales_owner", "execution_owner", "collection_owner"],
		)

	def test_status_bar_records_have_a_workflow_on_status(self):
		for doctype in records.owner_fields():
			field = frappe.db.get_value(
				"Workflow", {"document_type": doctype, "is_active": 1}, "workflow_state_field"
			)
			self.assertEqual(field, "status", doctype)
