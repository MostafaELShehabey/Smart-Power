"""S2 Station record (SP-76): the tabs each role sees, amounts only for money roles, the Costs tab."""

import json
from urllib.parse import parse_qs, urlsplit

import frappe
from frappe import _
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.sp_stations import station_tabs as st
from smart_power.sp_stations.costing import actual_cost
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
EXPENSE, CASH, CENTER = (
	"_Test Account Cost for Goods Sold - _TC",
	"_Test Cash - _TC",
	"_Test Cost Center - _TC",
)
SITE_TABS = ["overview", "scope", "site", "programming", "documents", "warranty"]
# every key a tab uses for money
MONEY_KEYS = {
	"amount",
	"agreed_amount",
	"grand_total",
	"labour_total",
	"rate",
	"total",
	"summary",
	"paid",
	"repaid_amount",
	"outstanding_amount",
	"discount_amount",
	"agreed",
	"estimated",
	"actual",
	"delta_amount",
}


def money_keys(data) -> set:
	"""The money keys with a value anywhere in a tab's answer."""
	found = set()
	if isinstance(data, dict):
		for key, value in data.items():
			if key in MONEY_KEYS and value is not None:
				found.add(key)
			found |= money_keys(value)
	elif isinstance(data, list):
		for value in data:
			found |= money_keys(value)
	return found


class TestStationRecord(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		st.seed_tab_access(force=True)
		cls.admin = make_user("sp.str.admin@example.com", ("admin",))
		cls.amira = make_user(
			"sp.str.amira@example.com",
			("project_manager", "contract_manager", "purchase_officer", "quote_creator"),
		)
		cls.mostafa = make_user(
			"sp.str.mostafa@example.com",
			(
				"installation_manager",
				"site_receiver",
				"commissioning_programmer",
				"warranty_service",
				"custody_holder",
			),
		)
		cls.collector = make_user("sp.str.collector@example.com", ("collection_officer",))
		cls.accountant = make_user("sp.str.accountant@example.com", ("accountant",))
		cls.winch = make_user("sp.str.winch@example.com", ("winch_manager",))
		cls.manager = make_user("sp.str.pm@example.com", ("project_manager",))

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		st.seed_tab_access(force=True)  # the class shares one transaction: undo a test's map edit
		quote = make_quotation(rate=200000, valid_days=3)
		quote.submit()
		frappe.db.set_value("SP Case", quote.sp_case, "accepted_quotation", quote.name)
		self.station = self.as_user(
			self.amira,
			lambda: frappe.get_doc(
				{"doctype": "SP Station", "case": quote.sp_case, "company": COMPANY}
			).insert(),
		)
		# the collection officer reads the stations they collect
		frappe.db.set_value("SP Station", self.station.name, "collection_owner", self.collector)

	def as_user(self, user, action):
		frappe.set_user(user)
		try:
			return action()
		finally:
			frappe.set_user("Administrator")

	def tabs(self, user):
		return self.as_user(user, lambda: st.tabs(self.station.name))

	def tab(self, user, name):
		return self.as_user(user, lambda: st.tab(self.station.name, name))

	def expense(self, event, amount, project=None):
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COMPANY,
				"posting_date": today(),
				"sp_posting_event": event,
				"accounts": [
					{
						"account": EXPENSE,
						"debit_in_account_currency": amount,
						"cost_center": CENTER,
						"project": project or self.station.project,
					},
					{"account": CASH, "credit_in_account_currency": amount, "cost_center": CENTER},
				],
			}
		).insert()
		je.submit()
		return je

	def test_mostafa_sees_the_six_site_tabs_and_no_amounts_anywhere(self):
		answer = self.tabs(self.mostafa)
		self.assertEqual((answer["tabs"], answer["amounts"]), (SITE_TABS, False))
		for name in SITE_TABS:
			self.assertEqual(money_keys(self.tab(self.mostafa, name)), set(), name)
		# when the customer paid is money too (found in the browser check)
		receive = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": COMPANY,
				"party_type": "Customer",
				"party": self.station.customer,
				"paid_from": "_Test Receivable - _TC",
				"paid_to": CASH,
				"paid_amount": 1000,
				"received_amount": 1000,
				"reference_no": "SP76",
				"reference_date": today(),
				"project": self.station.project,
			}
		).insert()
		receive.submit()
		paid = _("First payment confirmed")
		self.assertNotIn(paid, [e["label"] for e in self.tab(self.mostafa, "overview")["timeline"]])
		self.assertIn(paid, [e["label"] for e in self.tab(self.amira, "overview")["timeline"]])
		for name in ("agreement", "payments", "costs"):
			with self.assertRaises(frappe.PermissionError):
				self.tab(self.mostafa, name)

		# the form itself: the station's money fields are not sent to him
		def read():
			doc = frappe.get_doc("SP Station", self.station.name)
			doc.apply_fieldlevel_read_permissions()
			return doc

		doc = self.as_user(self.mostafa, read)
		self.assertIsNone(doc.get("agreed_amount"))
		self.assertEqual(doc.customer, self.station.customer)

	def test_amira_sees_ten_tabs_and_the_costs_tab_is_refused(self):
		answer = self.tabs(self.amira)
		self.assertEqual(len(answer["tabs"]), 10)
		self.assertNotIn("costs", answer["tabs"])
		self.assertTrue(answer["amounts"])
		with self.assertRaises(frappe.PermissionError):
			self.tab(self.amira, "costs")
		self.assertEqual(self.tab(self.amira, "payments")["summary"]["agreed"], 200000)

	def test_the_admin_sees_estimated_180000_against_actual_171500_with_the_indirect_share(self):
		frappe.db.set_value(
			"SP Station",
			self.station.name,
			"estimated_cost_snapshot",
			json.dumps({"frozen_on": today(), "lines": [], "total_cost": 180000}),
		)
		self.expense("Custody Expense", 120000)
		self.expense("Site Labour", 30000)
		self.expense("Winch Internal Charge", 15500)
		self.expense("Indirect Split", 6000)
		other = frappe.get_doc(
			{"doctype": "Project", "project_name": "SP76 other", "company": COMPANY}
		).insert()
		self.expense("Site Labour", 7777, project=other.name)  # another station's
		self.assertEqual(self.tabs(self.admin)["tabs"], list(st.TABS))
		costs = self.tab(self.admin, "costs")
		self.assertEqual(
			(costs["estimated"], costs["actual"], costs["indirect"], costs["direct"]),
			(180000, 171500, 6000, 165500),
		)
		self.assertEqual((costs["expected_profit"], costs["actual_profit"]), (20000, 28500))
		self.assertEqual(
			{line["source"]: line["amount"] for line in costs["lines"]},
			{"custody": 120000, "labour": 30000, "winch": 15500, "indirect": 6000},
		)

	def test_a_commission_agreed_on_the_contract_is_a_direct_cost(self):
		frappe.db.set_value("SP Station", self.station.name, "commission_amount", 5000)
		self.expense("Referrer Commission", 5000)  # SP-177's posting of the same commission
		self.assertEqual(actual_cost(self.station.name)["direct"], 5000)

	def test_the_other_roles_get_the_seeded_tabs(self):
		money = ["overview", "scope", "agreement", "payments", "documents", "history"]
		self.assertEqual(self.tabs(self.collector)["tabs"], money)
		self.assertEqual(self.tabs(self.accountant)["tabs"], money)  # Costs is the admin's only
		self.assertEqual(self.tabs(self.winch)["tabs"], ["overview", "site"])

	def test_the_admin_changes_the_map_and_a_user_sees_the_tabs_of_all_their_roles(self):
		settings = frappe.get_single("Smart Power Settings")
		for row in settings.station_tab_access:
			if row.role == "SP Winch Manager":
				row.tab_documents = 1
		set_setting(station_tab_access=settings.station_tab_access)
		self.assertEqual(self.tabs(self.winch)["tabs"], ["overview", "site", "documents"])
		both = make_user("sp.str.both@example.com", ("winch_manager", "site_receiver"))
		self.assertEqual(self.tabs(both)["tabs"], SITE_TABS)

	def test_a_non_cost_role_never_gets_the_costs_tab(self):
		settings = frappe.get_single("Smart Power Settings")
		for row in settings.station_tab_access:
			if row.role == "SP Winch Manager":
				row.tab_costs = 1
		set_setting(station_tab_access=settings.station_tab_access)
		self.assertNotIn("costs", self.tabs(self.winch)["tabs"])

	def test_supplier_prices_are_for_the_purchase_officer_and_the_admin(self):
		self.assertTrue(self.tab(self.amira, "purchasing")["supplier_prices"])
		self.assertFalse(self.tab(self.manager, "purchasing")["supplier_prices"])

	def test_the_schedule_shows_each_instalments_status(self):
		past, future = add_days(today(), -10), add_days(today(), 20)
		rows = st.schedule_status([(past, 100), (past, 100), (future, 100)], 150)
		self.assertEqual([r["status"] for r in rows], ["Paid", "Overdue", "Due"])
		self.assertEqual([r["paid"] for r in rows], [100, 50, 0])

	def test_the_contract_pdf_link_is_encoded_once(self):
		# BUG-9: the page used to encode an already encoded link: Frappe got "Sales%2520Order"
		contract = "SAL-ORD-2026-00001"
		url = st.contract_pdf_url(contract)
		self.assertTrue(url.startswith("/api/method/frappe.utils.print_format.download_pdf?"))
		self.assertEqual(
			parse_qs(urlsplit(url).query),
			{"doctype": ["Sales Order"], "name": [contract], "format": ["SP Contract"]},
		)
		frappe.db.set_value("SP Station", self.station.name, "sales_order", contract)
		self.assertEqual(self.tab(self.admin, "documents")["contract"]["pdf"], url)

	def test_history_hides_the_cost_changes_from_who_cannot_see_cost(self):
		frappe.get_doc(
			{
				"doctype": "Version",
				"ref_doctype": "SP Station",
				"docname": self.station.name,
				"data": json.dumps(
					{
						"changed": [
							["commission_amount", 0, 5000],
							["location_text", "", "الواحات"],
							["agreed_amount", None, 0],
						]
					}
				),
			}
		).insert(ignore_permissions=True)
		fields = [c["field"] for c in self.tab(self.collector, "history")["changes"]]
		self.assertIn("Location", fields)
		self.assertNotIn("Agreed", fields)  # empty to zero is no change (found in the browser check)
		self.assertNotIn("Referrer Commission", fields)
		admin_fields = [c["field"] for c in self.tab(self.admin, "history")["changes"]]
		self.assertIn("Referrer Commission", admin_fields)
		self.assertTrue(self.tab(self.collector, "history")["owners"])
