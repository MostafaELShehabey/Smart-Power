"""Item catalogue fields and categories (SP-29)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.setup.seed import defaults
from smart_power.sp_stock.item import seed_item_groups
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()


def make_item(code, **kw):
	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": kw.pop("item_name", code),
			"item_group": kw.pop("item_group", "_Test Item Group"),
			"stock_uom": "_Test UOM",
			**kw,
		}
	).insert()


class TestItemFields(IntegrationTestCase):
	def test_panel_with_specs(self):
		item = make_item(
			"PNL-RISEN-710-T",
			item_name="RISEN 710 W",
			sp_name_ar="لوح RISEN 710 وات",
			sp_watt=710,
			sp_vmp=40.1,
			sp_voc=48.2,
			sp_imp=17.7,
			sp_isc=18.6,
		)
		self.assertEqual((item.sp_name_ar, item.sp_watt), ("لوح RISEN 710 وات", 710))

	def test_impossible_specs_are_refused(self):
		for code, specs in (
			("INV-BAD-T", {"sp_mppt_min": 800, "sp_mppt_max": 200}),
			("PNL-BAD-V-T", {"sp_vmp": 50, "sp_voc": 40}),
			("PNL-BAD-I-T", {"sp_imp": 20, "sp_isc": 18}),
		):
			with self.assertRaises(frappe.ValidationError, msg=code):
				make_item(code, **specs)

	def test_fields_are_developer_owned(self):
		for fieldname in ("sp_name_ar", "sp_watt", "sp_mppt_max", "sp_hp", "sp_catalogue"):
			self.assertEqual(frappe.db.get_value("Custom Field", f"Item-{fieldname}", "module"), "SP Stock")

	def test_catalogue_groups_are_seeded(self):
		seed_item_groups()
		root = frappe.db.get_value("Item Group", {"lft": 1}, "name")
		for name in defaults()["item_groups"]["names"]:
			self.assertEqual(frappe.db.get_value("Item Group", name, "parent_item_group"), root, name)
		seed_item_groups()  # a second run adds nothing
		self.assertEqual(
			frappe.db.count("Item Group", {"name": ("in", defaults()["item_groups"]["names"])}),
			len(defaults()["item_groups"]["names"]),
		)

	def test_child_groups_for_the_pump_template(self):
		# SP-56: motors and pumps are told apart by group, and share the pumps' price category
		seed_item_groups()
		for parent, names in defaults()["item_groups"]["children"].items():
			self.assertTrue(frappe.db.get_value("Item Group", parent, "is_group"), parent)
			for name in names:
				group = frappe.db.get_value(
					"Item Group",
					name,
					["parent_item_group", "sp_price_age_category", "sp_code_prefix"],
					as_dict=True,
				)
				self.assertEqual(group.parent_item_group, parent, name)
				self.assertEqual(group.sp_price_age_category, parent, name)
				self.assertTrue(group.sp_code_prefix, name)
		self.assertEqual(frappe.db.get_value("Item Group", "مواتير غاطس", "sp_required_specs"), "sp_hp")
