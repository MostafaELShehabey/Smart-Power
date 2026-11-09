"""X4 Lists screen (SP-32)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services import lists
from smart_power.tests.test_lists import DT, make


class TestX4Lists(IntegrationTestCase):
	def test_get_list_includes_inactive_values(self):
		off = make(code="OFF_X4")
		lists.set_active(off.name, 0)
		self.assertFalse(frappe.db.get_value(DT, off.name, "is_active"))
		self.assertIn("OFF_X4", {v.code for v in lists.get_list("Region")})

	def test_reorder(self):
		for code in ("R_ONE", "R_TWO", "R_THREE"):
			make(list_name="Inverter Brand", code=code)
		names = [v.name for v in lists.get_list("Inverter Brand")]
		lists.reorder("Inverter Brand", list(reversed(names)))
		self.assertEqual([v.name for v in lists.get_list("Inverter Brand")], list(reversed(names)))

	def test_reorder_needs_the_whole_list(self):
		make(list_name="Inverter Brand", code="ONLY_ONE")
		make(list_name="Inverter Brand", code="ONLY_TWO")
		with self.assertRaises(frappe.ValidationError):
			lists.reorder("Inverter Brand", ["Inverter Brand-ONLY_ONE"])

	def test_unknown_list_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			lists.get_list("Nope")

	def test_page_is_for_the_admin(self):
		roles = {r.role for r in frappe.get_doc("Page", "sp-lists").roles}
		self.assertEqual(roles, {"SP Admin", "System Manager"})
