"""Cost and supplier prices for cost roles only (SP-35, price part)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.permissions import COST_KEYS, can_see_cost, strip_cost
from smart_power.sp_core.setup.role_catalogue import ROLES
from smart_power.sp_stock import prices
from smart_power.sp_stock.prices import BTC, COST
from smart_power.tests.test_prices import make_item
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()


class TestCostVisibility(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.camelia = make_user("sp.vis.camelia@example.com", ("lead_intake", "customer_followup"))
		cls.aya = make_user("sp.vis.aya@example.com", ("quote_creator", "catalog_manager", "pricing_manager"))
		cls.gaber = make_user("sp.vis.gaber@example.com", ("main_store_keeper", "installation_technician"))
		# someone the admin gave ERPNext's price-list role by hand, without a cost role
		cls.helper = make_user(
			"sp.vis.helper@example.com", ("showroom_sales",), extra_roles=("Sales Master Manager",)
		)
		item = make_item("SP-VIS-TEST-" + frappe.generate_hash(length=6)).name
		cls.cost_row, _ = prices.set_price(item, COST, 870)
		cls.sale_row, _ = prices.set_price(item, BTC, 1270)
		cls.item = item

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_cost_roles_follow_the_catalogue(self):
		keys = {r.key for r in ROLES if r.sees_cost}
		self.assertEqual(
			keys,
			{
				"admin",
				"accountant",
				"quote_creator",
				"system_designer",
				"pricing_manager",
				"purchase_officer",
				"supplier_accounts",
			},
		)

	def test_who_sees_cost(self):
		self.assertTrue(can_see_cost(self.aya))
		self.assertTrue(can_see_cost("Administrator"))
		self.assertFalse(can_see_cost(self.camelia))
		self.assertFalse(can_see_cost(self.gaber))
		self.assertFalse(can_see_cost(self.helper))

	def test_api_payloads_lose_the_cost_keys(self):
		data = {"price": 1270, **{k: 1 for k in COST_KEYS}}
		self.assertEqual(strip_cost(data, self.camelia), {"price": 1270})
		self.assertEqual(strip_cost(data, self.aya), data)

	def test_followup_cannot_read_item_prices_directly(self):
		# sale prices reach كاميليا only through the I2 API, which strips the cost
		self.assertFalse(frappe.has_permission("Item Price", "read", user=self.camelia))

	def test_buying_rows_are_hidden_from_non_cost_users(self):
		frappe.set_user(self.helper)
		visible = set(frappe.get_list("Item Price", {"item_code": self.item}, pluck="name"))
		self.assertEqual(visible, {self.sale_row})
		self.assertFalse(frappe.has_permission("Item Price", "read", doc=self.cost_row, user=self.helper))
		self.assertTrue(frappe.has_permission("Item Price", "read", doc=self.sale_row, user=self.helper))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Item Price", self.cost_row).check_permission("read")

	def test_cost_users_see_both(self):
		frappe.set_user(self.aya)
		visible = set(frappe.get_list("Item Price", {"item_code": self.item}, pluck="name"))
		self.assertEqual(visible, {self.sale_row, self.cost_row})
