"""Warehouses by location (SP-28): main store, showroom store, one site per station, transit."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.setup.seed import defaults
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()

COMPANY = "_Test Company"


def make_project(title=None):
	title = title or "SP Station " + frappe.generate_hash(length=6)
	return frappe.get_doc({"doctype": "Project", "project_name": title, "company": COMPANY}).insert().name


class TestWarehouseTree(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def test_types_and_tree(self):
		for name in wh.SP_TYPES:
			self.assertTrue(frappe.db.exists("Warehouse Type", name), name)
		spec = defaults()["warehouses"]
		main = wh.warehouse_of(COMPANY, wh.MAIN)
		showroom = wh.warehouse_of(COMPANY, wh.SHOWROOM)
		self.assertEqual(frappe.db.get_value("Warehouse", main, "warehouse_name"), spec["main"])
		self.assertEqual(frappe.db.get_value("Warehouse", showroom, "warehouse_name"), spec["showroom"])
		self.assertTrue(frappe.db.get_value("Warehouse", wh.sites_group(COMPANY), "is_group"))
		self.assertTrue(wh.warehouse_of(COMPANY, wh.TRANSIT))

	def test_seed_runs_again_without_duplicates(self):
		before = frappe.db.count("Warehouse", {"company": COMPANY})
		wh.seed_warehouses(COMPANY)
		self.assertEqual(frappe.db.count("Warehouse", {"company": COMPANY}), before)

	def test_empty_default_stores_are_disabled_and_the_default_is_a_live_store(self):
		stores = frappe.db.get_value("Warehouse", {"warehouse_name": "Stores", "company": COMPANY})
		if stores and not frappe.db.exists("Stock Ledger Entry", {"warehouse": stores}):
			self.assertTrue(frappe.db.get_value("Warehouse", stores, "disabled"))
		default = frappe.db.get_value("Company", COMPANY, "default_warehouse")
		self.assertFalse(frappe.db.get_value("Warehouse", default, "disabled"))

	def test_no_consignment_warehouse_type(self):
		# Africa System's panels are counted on their containers (SP-91), never in a ledger warehouse
		self.assertFalse(frappe.get_all("Warehouse Type", {"name": ("like", "%onsign%")}))


class TestSiteWarehouses(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def test_first_use_creates_the_site_warehouse_once(self):
		project = make_project()
		self.assertIsNone(wh.site_warehouse(project, create=False))
		site = wh.site_warehouse(project)
		row = frappe.db.get_value(
			"Warehouse", site, ["warehouse_type", "sp_project", "parent_warehouse", "company"], as_dict=True
		)
		self.assertEqual(
			(row.warehouse_type, row.sp_project, row.parent_warehouse, row.company),
			(wh.SITE, project, wh.sites_group(COMPANY), COMPANY),
		)
		self.assertEqual(wh.site_warehouse(project), site)

	def _warehouse(self, **kw):
		return frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": "SP test " + frappe.generate_hash(length=6),
				"company": COMPANY,
				"parent_warehouse": wh.sites_group(COMPANY),
				**kw,
			}
		)

	def test_site_warehouse_needs_a_project(self):
		with self.assertRaises(frappe.ValidationError):
			self._warehouse(warehouse_type=wh.SITE).insert()

	def test_one_site_warehouse_per_station(self):
		project = make_project()
		wh.site_warehouse(project)
		with self.assertRaises(frappe.ValidationError):
			self._warehouse(warehouse_type=wh.SITE, sp_project=project).insert()

	def test_only_site_warehouses_link_a_project(self):
		with self.assertRaises(frappe.ValidationError):
			self._warehouse(warehouse_type=wh.MAIN, sp_project=make_project()).insert()

	def test_site_warehouse_is_not_a_group(self):
		with self.assertRaises(frappe.ValidationError):
			self._warehouse(warehouse_type=wh.SITE, sp_project=make_project(), is_group=1).insert()
