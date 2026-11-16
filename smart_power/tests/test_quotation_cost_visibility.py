"""Cost, profit and hidden lines on quotes: the quote's creator and the admin only (SP-35, SP-54)."""

from unittest.mock import patch

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
		self.case = case_for_test_customer(follow_up_owner=self.camelia, quote_creator=self.aya)
		self.quote = quote_for(self.case, rate=1000)

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

	def test_another_quote_creator_sees_neither_the_quote_nor_its_cost(self):
		other = make_user("sp.costvis.other@example.com", ("quote_creator",))
		frappe.set_user(other)
		try:
			self.assertNotIn(self.quote.name, frappe.get_list("Quotation", pluck="name"))
			self.assertFalse(frappe.has_permission("Quotation", "read", self.quote.name))
		finally:
			frappe.set_user("Administrator")
		# with the case shared, the quote reads but its cost stays out
		frappe.db.set_value("SP Case", self.case.name, "requested_by", other)
		data = fetch_as(other, self.quote.name)
		self.assertTrue(data["grand_total"])
		self.assertFalse(data["sp_total_cost"])  # REST sends 0 for what she may not read
		self.assertFalse(data["items"][0]["sp_cost"])
		frappe.set_user(other)
		try:
			view = get_quote_view(self.quote.name)
		finally:
			frappe.set_user("Administrator")
		self.assertNotIn("sp_total_cost", view)  # the quote view leaves the keys out
		self.assertNotIn("sp_cost", view["items"][0])

	def test_hidden_lines_are_absent_from_rest_view_and_print_for_camelia(self):
		self.quote.append(
			"items", {"sp_line_kind": "Commission", "item_name": "عمولة سرية", "qty": 1, "sp_cost": 5000}
		)
		self.quote.save()
		self.assertEqual(len(fetch_as(self.camelia, self.quote.name)["items"]), 1)
		frappe.set_user(self.camelia)
		try:
			self.assertEqual(len(get_quote_view(self.quote.name)["items"]), 1)
			# CI skips building assets; the print view looks bundles up in assets.json
			with patch("frappe.utils.get_assets_json", return_value=frappe.utils.get_assets_json() or {}):
				html = frappe.get_print("Quotation", self.quote.name, "Standard")
		finally:
			frappe.set_user("Administrator")
		self.assertNotIn("عمولة سرية", html)
		self.assertEqual(len(fetch_as(self.aya, self.quote.name)["items"]), 2)  # her own quote
		self.assertIn("عمولة سرية", [r.item_name for r in frappe.get_doc("Quotation", self.quote.name).items])

	def test_a_save_without_the_hidden_lines_and_cost_keeps_them(self):
		self.quote.append(
			"items", {"sp_line_kind": "Commission", "item_name": "عمولة", "qty": 1, "sp_cost": 5000}
		)
		self.quote.save()
		frappe.db.set_value("SP Case", self.case.name, "follow_up_owner", self.aya)  # still hers
		other = make_user("sp.costvis.saver@example.com", ("quote_creator",))
		frappe.db.set_value("SP Case", self.case.name, "requested_by", other)
		frappe.set_user(other)
		try:
			doc = frappe.get_doc("Quotation", self.quote.name)
			doc.apply_fieldlevel_read_permissions()
			self.assertEqual(len(doc.items), 1)
			doc.items[0].sp_cost = None
			doc.save()
		finally:
			frappe.set_user("Administrator")
		saved = frappe.get_doc("Quotation", self.quote.name)
		self.assertEqual(len(saved.items), 2)
		self.assertEqual(saved.sp_total_cost, 700 + 5000)
