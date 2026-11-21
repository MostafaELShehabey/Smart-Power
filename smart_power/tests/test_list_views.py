"""The list pattern (SP-45): saved-view tabs and the totals row."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power import lists
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()


class TestListViews(IntegrationTestCase):
	def setUp(self):
		lists.seed_list_views()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_stations_list_has_the_s1_views(self):
		views = lists.views_for("Administrator")
		station = {v["label"]: v["filters"] for v in views["SP Station"]}
		# SP-77 S1: Open · Installing · Collecting · Overdue · Closed, between Mine and All
		self.assertEqual(
			list(station)[:7], ["Mine", "Open", "Installing", "Collecting", "Overdue", "Closed", "All"]
		)
		self.assertEqual(station["Overdue"], [["has_overdue", "=", 1]])  # only overdue stations

	def test_a_tab_shows_only_to_its_roles(self):
		view = frappe.get_doc(
			{
				"doctype": "SP List View",
				"list_doctype": "SP Station",
				"label": "Finance only",
				"sort_order": 9,
				"roles": "SP Accountant",
				"filters": json.dumps([["has_overdue", "=", 1]]),
			}
		).insert()
		self.addCleanup(frappe.delete_doc, "SP List View", view.name, force=True)
		accountant = make_user("sp.lists.accountant@example.com", ("accountant",))
		clerk = make_user("sp.lists.clerk@example.com", ("project_manager",))
		labels = lambda user: [v["label"] for v in lists.views_for(user).get("SP Station", [])]  # noqa: E731
		self.assertIn("Finance only", labels(accountant))
		self.assertNotIn("Finance only", labels(clerk))

	def test_the_totals_row_sums_every_matching_row(self):
		case = case_for_test_customer()
		quote_for(case, rate=1000)
		quote_for(case, rate=2500)
		result = lists.totals(
			"Quotation", [["Quotation", "sp_case", "=", case.name]], ["grand_total", "customer_name"]
		)
		self.assertEqual(flt(result["grand_total"]), 3500)
		self.assertNotIn("customer_name", result)  # money columns only
