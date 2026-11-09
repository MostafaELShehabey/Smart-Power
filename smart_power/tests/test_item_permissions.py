"""Only the catalog manager and the admin add or edit items; everyone else reads (SP-29)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.setup.role_catalogue import ROLES
from smart_power.tests.utils import make_user


class TestItemPermissions(IntegrationTestCase):
	def test_catalog_manager_edits_items(self):
		aya = make_user("sp.item.aya@example.com", ("system_designer", "quote_creator", "catalog_manager"))
		for ptype in ("read", "write", "create"):
			self.assertTrue(frappe.has_permission("Item", ptype, user=aya), ptype)

	def test_store_keeper_only_reads(self):
		# محمد جابر: main store keeper and installation technician
		gaber = make_user("sp.item.gaber@example.com", ("main_store_keeper", "installation_technician"))
		self.assertTrue(frappe.has_permission("Item", "read", user=gaber))
		for ptype in ("write", "create", "delete"):
			self.assertFalse(frappe.has_permission("Item", ptype, user=gaber), ptype)

	def test_pricing_manager_edits_prices_not_items(self):
		# أميرة holds pricing_manager: she sets prices but does not change the catalogue
		amira = make_user(
			"sp.item.amira@example.com",
			("quote_creator", "contract_manager", "project_manager", "purchase_officer", "pricing_manager"),
		)
		self.assertFalse(frappe.has_permission("Item", "write", user=amira))
		self.assertFalse(frappe.has_permission("Item", "create", user=amira))
		self.assertTrue(frappe.has_permission("Item Price", "write", user=amira))
		self.assertTrue(frappe.has_permission("Price List", "write", user=amira))

	def test_only_catalog_and_admin_keys_get_item_manager(self):
		keys = {r.key for r in ROLES if "Item Manager" in r.erpnext_roles}
		self.assertEqual(keys, {"catalog_manager", "admin"})
