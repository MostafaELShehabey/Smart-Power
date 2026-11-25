"""BUG-28: the store keeper never sees what the goods cost. Stock values sit at the cost permlevel
on ERPNext's stock records (forms, lists, report view, a report's "Add column", exports), and the
reports that show values open for the cost roles only."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.permissions import (
	COST_PERMLEVEL,
	STOCK_COST_DOCTYPES,
	STOCK_COST_FIELDS,
	VALUE_REPORTS,
	get_data_for_custom_field,
	sync_cost_permissions,
	sync_cost_reports,
)
from smart_power.sp_core.permissions_matrix import FIELD_LABELS, FIELD_RULES
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY, ITEM = "_Test Company", "_Test Item"
SOURCE, TARGET = "_Test Warehouse - _TC", "_Test Warehouse 1 - _TC"
LAST_PRICE, RECEIPT_RATE, TYPED_RATE = 123, 10, 999


class TestStockCostVisibility(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		sync_cost_permissions()
		sync_cost_reports()
		cls.keeper = make_user("sp.stock.keeper@example.com", ("main_store_keeper",))
		cls.technician = make_user("sp.stock.tech@example.com", ("installation_technician",))
		cls.accountant = make_user("sp.stock.accountant@example.com", ("accountant",))

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_every_stock_value_field_is_at_the_cost_level(self):
		for doctype, fields in STOCK_COST_FIELDS.items():
			meta = frappe.get_meta(doctype)
			for fieldname in fields:
				with self.subTest(doctype=doctype, field=fieldname):
					self.assertEqual(meta.get_field(fieldname).permlevel, COST_PERMLEVEL)

	def test_each_child_table_follows_a_listed_parent(self):
		# a child table's fields are read through its parent's permission rules
		for doctype in STOCK_COST_FIELDS:
			if not frappe.get_meta(doctype).istable:
				self.assertIn(doctype, STOCK_COST_DOCTYPES)
				continue
			parents = frappe.get_all("DocField", {"fieldtype": "Table", "options": doctype}, pluck="parent")
			with self.subTest(child=doctype):
				self.assertTrue(set(parents) & set(STOCK_COST_DOCTYPES))

	def test_the_store_keeper_cannot_add_a_cost_column(self):
		frappe.db.set_value("Item", ITEM, "last_purchase_rate", LAST_PRICE)
		frappe.set_user(self.keeper)
		rows = frappe.get_list("Item", {"name": ITEM}, ["name", "last_purchase_rate", "valuation_rate"])
		self.assertEqual(rows[0].get("last_purchase_rate"), None)
		self.assertEqual(rows[0].get("valuation_rate"), None)
		# "Add column" on a report is refused with a message, not a server error
		with self.assertRaises(frappe.PermissionError):
			get_data_for_custom_field("Item", "last_purchase_rate", [ITEM])
		self.assertEqual(get_data_for_custom_field("Item", "item_name", [ITEM]).get(ITEM), ITEM)
		frappe.set_user(self.accountant)
		self.assertEqual(
			get_data_for_custom_field("Item", "last_purchase_rate", [ITEM]).get(ITEM), LAST_PRICE
		)

	def test_the_store_keeper_reads_no_stock_value(self):
		frappe.set_user(self.keeper)
		for doctype in ("Stock Ledger Entry", "Stock Entry", "Bin", "Item"):
			with self.subTest(doctype=doctype):
				self.assertNotIn(COST_PERMLEVEL, frappe.get_meta(doctype).get_permlevel_access("read"))
		frappe.set_user(self.accountant)
		self.assertIn(COST_PERMLEVEL, frappe.get_meta("Stock Ledger Entry").get_permlevel_access("read"))

	def test_the_technician_does_not_read_the_project_costing(self):
		frappe.set_user(self.technician)
		self.assertNotIn(COST_PERMLEVEL, frappe.get_meta("Project").get_permlevel_access("read"))

	def test_the_value_reports_open_for_the_cost_roles_only(self):
		for report in VALUE_REPORTS:
			if not frappe.db.exists("Report", report):
				continue
			doc = frappe.get_doc("Report", report)
			with self.subTest(report=report):
				frappe.set_user(self.keeper)
				self.assertFalse(doc.is_permitted())
				frappe.set_user(self.accountant)
				self.assertTrue(doc.is_permitted())
		frappe.set_user(self.keeper)
		# his quantities stay with him (SP-87)
		self.assertTrue(frappe.get_doc("Report", "SP Stock by Owner").is_permitted())

	def test_the_admins_own_report_roles_are_kept(self):
		report = VALUE_REPORTS[0]
		name = frappe.db.get_value("Custom Role", {"report": report})
		doc = frappe.get_doc("Custom Role", name)
		doc.append("roles", {"role": "Stock User"})
		doc.save(ignore_permissions=True)
		try:
			sync_cost_reports()
			roles = [r.role for r in frappe.get_doc("Custom Role", name).roles]
			self.assertIn("Stock User", roles)
		finally:
			doc = frappe.get_doc("Custom Role", name)
			doc.set("roles", [r for r in doc.roles if r.role != "Stock User"])
			doc.save(ignore_permissions=True)

	def test_a_transfer_by_the_store_keeper_still_values_the_goods(self):
		receipt = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": COMPANY,
				"items": [
					{"item_code": ITEM, "qty": 5, "t_warehouse": SOURCE, "basic_rate": RECEIPT_RATE},
				],
			}
		).insert()
		receipt.submit()
		frappe.set_user(self.keeper)
		transfer = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Transfer",
				"company": COMPANY,
				"items": [
					{
						"item_code": ITEM,
						"qty": 1,
						"s_warehouse": SOURCE,
						"t_warehouse": TARGET,
						# typed by someone who may not set it: ERPNext prices it from the stock
						"basic_rate": TYPED_RATE,
					}
				],
			}
		).insert()
		transfer.submit()
		frappe.set_user("Administrator")
		rate = frappe.db.get_value("Stock Entry Detail", {"parent": transfer.name}, "basic_rate")
		self.assertNotEqual(rate, TYPED_RATE)
		self.assertTrue(rate > 0)

	def test_the_matrix_has_a_stock_values_tick(self):
		self.assertEqual({dt for dt, _level in FIELD_RULES["stock_values"]}, set(STOCK_COST_DOCTYPES))
		self.assertIn("stock_values", FIELD_LABELS)
