"""Pickers show only the active values of one list (SP-32)."""

import json

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services import lists
from smart_power.tests.test_lists import DT, make


class TestListPickers(IntegrationTestCase):
	def test_pickers_show_active_values_only(self):
		make(code="ON_1")
		off = make(code="OFF_1")
		frappe.db.set_value(DT, off.name, "is_active", 0)
		active = {v.code for v in lists.get_values("Region")}
		every = {v.code for v in lists.get_values("Region", active_only=False)}
		self.assertIn("ON_1", active)
		self.assertNotIn("OFF_1", active)
		self.assertIn("OFF_1", every)

	def test_link_filters(self):
		self.assertEqual(
			json.loads(lists.link_filters("Region")),
			[[DT, "list_name", "=", "Region"], [DT, "is_active", "=", 1]],
		)
		for doctype, fieldname in (
			("SP Margin Range", "offer_type"),
			("SP Rule Setting", "scope_offer_type"),
		):
			field = frappe.get_meta(doctype).get_field(fieldname)
			self.assertEqual(json.loads(field.link_filters), json.loads(lists.link_filters("System Type")))

	def test_old_record_keeps_a_deactivated_value(self):
		parent = make(code="PARENT_B")
		child = make(code="CHILD_B", parent_value=parent.name)
		frappe.get_doc(DT, parent.name).update({"is_active": 0}).save()
		child.reload()
		child.value_en = "still saves"
		child.save()
		self.assertEqual(child.parent_value, parent.name)
