"""Cost and profit on quotes are for the cost roles only (SP-35, SP-54)."""

import frappe
from frappe.client import get as rest_get
from frappe.tests import IntegrationTestCase

from smart_power.permissions import COST_PERMLEVEL, get_quote_view, sync_cost_permissions
from smart_power.sp_stock.prices import COST, set_price
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import make_user

COST_KEYS = ("sp_total_cost", "sp_profit", "sp_margin_pct")


def fetch_as(user, name):
	frappe.set_user(user)
	try:
		return rest_get("Quotation", name)
	finally:
		frappe.set_user("Administrator")


class TestQuotationCostVisibility(IntegrationTestCase):
	def setUp(self):
		sync_cost_permissions()
		set_price("_Test Item", COST, 700, supplier="_Test Supplier", reason="SP-54 test")
		self.aya = make_user("sp.costvis.aya@example.com", ("quote_creator",))
		self.camelia = make_user(
			"sp.costvis.camelia@example.com", ("lead_intake", "customer_followup", "followup_all")
		)
		self.quote = quote_for(case_for_test_customer(follow_up_owner=self.camelia), rate=1000)

	def test_follow_up_owner_gets_no_cost_over_rest(self):
		# plain REST: Frappe hides the values (0) of fields she may not read
		data = fetch_as(self.camelia, self.quote.name)
		self.assertTrue(data.get("grand_total"))
		self.assertFalse(data.get("sp_total_cost"))
		self.assertFalse(data["items"][0].get("sp_cost"))

	def test_quote_view_leaves_the_cost_keys_out(self):
		# the acceptance check: the follow-up owner's quote has no cost or profit keys
		frappe.set_user(self.camelia)
		try:
			data = get_quote_view(self.quote.name)
		finally:
			frappe.set_user("Administrator")
		for key in COST_KEYS:
			self.assertNotIn(key, data, key)
		self.assertNotIn("sp_cost", data["items"][0])
		self.assertNotIn("sp_line_profit", data["items"][0])
		self.assertTrue(data["grand_total"])
		frappe.set_user(self.aya)
		try:
			self.assertEqual(get_quote_view(self.quote.name)["sp_total_cost"], 700)
		finally:
			frappe.set_user("Administrator")

	def test_quote_creator_sees_cost(self):
		data = fetch_as(self.aya, self.quote.name)
		self.assertEqual(data["sp_total_cost"], 700)
		self.assertEqual(data["items"][0]["sp_cost"], 700)

	def test_only_cost_roles_hold_the_cost_permlevel(self):
		roles = set(
			frappe.get_all(
				"Custom DocPerm", {"parent": "Quotation", "permlevel": COST_PERMLEVEL}, pluck="role"
			)
		)
		self.assertIn("SP Quote Creator", roles)
		self.assertNotIn("SP Customer Followup", roles)
		self.assertNotIn("Sales User", roles)
