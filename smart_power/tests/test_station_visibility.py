"""Stations by assignment, and read-only after the contract with its banner (SP-35)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.permissions import set_read_only_banner
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"
PROJECTS_MANAGER = (
	"quote_creator",
	"contract_manager",
	"project_manager",
	"purchase_officer",
	"pricing_manager",
	"winch_reviewer",
)


def as_user(user, fn):
	frappe.set_user(user)
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")


class TestStationVisibility(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		self.aya = make_user("sp.stv.aya@example.com", ("quote_creator",))
		self.hussein = make_user("sp.stv.hussein@example.com", ("lead_intake", "customer_followup"))
		self.other = make_user("sp.stv.other@example.com", ("lead_intake", "customer_followup"))
		self.amira = make_user("sp.stv.amira@example.com", PROJECTS_MANAGER)
		frappe.db.set_value(
			"User", self.amira, {"first_name": "أميرة", "last_name": "", "full_name": "أميرة"}
		)
		getattr(frappe.local, "fullnames", {}).pop(self.amira, None)
		self.case = case_for_test_customer(follow_up_owner=self.hussein, quote_creator=self.aya)
		self.quote = quote_for(self.case, rate=1000)
		self.quote.submit()
		approve_version(self.quote.name)
		self.station = as_user(self.amira, lambda: make_contract(self.case.name))["station"]
		frappe.db.set_value("SP Case", self.case.name, "status", "Won")
		frappe.db.set_value("SP Station", self.station, "execution_owner", self.amira)

	def tearDown(self):
		frappe.set_user("Administrator")

	def listed(self, user):
		return as_user(user, lambda: frappe.get_list("SP Station", pluck="name"))

	def test_the_quote_creator_reads_the_station_after_the_contract_with_the_banner(self):
		self.assertIn(self.station, self.listed(self.aya))
		self.assertTrue(frappe.has_permission("SP Station", "read", self.station, user=self.aya))
		self.assertFalse(frappe.has_permission("SP Station", "write", self.station, user=self.aya))
		doc = as_user(self.aya, lambda: frappe.get_doc("SP Station", self.station))
		frappe.set_user(self.aya)
		set_read_only_banner(doc)
		frappe.set_user("Administrator")
		self.assertIn("أميرة", doc.get_onload().get("sp_read_only"))

	def test_the_case_and_quote_are_read_only_for_sales_after_the_contract(self):
		for doctype, name in (("SP Case", self.case.name), ("Quotation", self.quote.name)):
			for user in (self.aya, self.hussein):
				self.assertTrue(frappe.has_permission(doctype, "read", name, user=user), (doctype, user))
				self.assertFalse(frappe.has_permission(doctype, "write", name, user=user), (doctype, user))
			self.assertTrue(frappe.has_permission(doctype, "read", name, user=self.amira))
		self.assertTrue(frappe.has_permission("SP Case", "write", self.case.name, user=self.amira))

	def test_a_station_is_seen_by_whoever_is_assigned_to_it(self):
		self.assertNotIn(self.station, self.listed(self.other))
		self.assertFalse(frappe.has_permission("SP Station", "read", self.station, user=self.other))
		frappe.db.set_value("SP Station", self.station, "sales_owner", self.other)
		self.assertIn(self.station, self.listed(self.other))
		self.assertFalse(frappe.has_permission("SP Station", "write", self.station, user=self.other))
		self.assertIn(self.station, self.listed(self.amira))  # the projects manager sees all

	def test_the_projects_manager_gets_no_costs_tab_and_no_banner(self):
		doc = frappe.get_doc("SP Station", self.station)
		access = as_user(self.amira, lambda: doc.get_permlevel_access("read"))
		cost_level = frappe.get_meta("SP Station").get_field("cost_section").permlevel
		self.assertNotIn(cost_level, access)
		frappe.set_user(self.amira)
		set_read_only_banner(doc)
		frappe.set_user("Administrator")
		self.assertFalse(doc.get_onload().get("sp_read_only"))
