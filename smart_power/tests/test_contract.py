"""The contract: a Sales Order from the approved quote version (SP-74, and SP-59's option B)."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_sales.quotation import approve_version, new_option
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"


class TestContract(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		self.amira = make_user("sp.ct.amira@example.com", ("project_manager", "contract_manager"))
		frappe.db.set_value("Item", "_Test Item", "sp_warranty_years", 5)
		self.a = make_quotation(rate=100000, valid_days=3)
		self.a.items[0].sp_cost = 70000
		self.a.save()
		self.b = frappe.get_doc("Quotation", new_option(self.a.name))
		self.b.items[0].rate = 120000
		self.b.save()
		self.case = self.a.sp_case
		for q in (self.a, self.b):
			frappe.get_doc("Quotation", q.name).submit()

	def tearDown(self):
		frappe.set_user("Administrator")

	def contract(self, **kw):
		frappe.set_user(self.amira)
		try:
			return make_contract(self.case, **kw)
		finally:
			frappe.set_user("Administrator")

	def test_signed_first_then_the_deposit_reuses_the_order_and_freezes_the_estimate(self):
		approve_version(self.a.name)
		first = self.contract()
		self.assertTrue(first["created"])
		so = frappe.get_doc("Sales Order", first["sales_order"])
		self.assertFalse(so.sp_estimate_frozen_on)
		again = self.contract(at_deposit=True)
		self.assertEqual((again["sales_order"], again["created"]), (first["sales_order"], False))
		self.assertEqual(frappe.db.count("Sales Order", {"sp_case": self.case, "docstatus": ("<", 2)}), 1)
		self.assertTrue(frappe.db.get_value("Sales Order", so.name, "sp_estimate_frozen_on"))
		snapshot = json.loads(frappe.db.get_value("SP Station", first["station"], "estimated_cost_snapshot"))
		self.assertEqual(snapshot["total_cost"], 70000)

	def test_order_station_and_project_link_one_to_one(self):
		approve_version(self.a.name)
		result = self.contract()
		station = frappe.get_doc("SP Station", result["station"])
		so = frappe.get_doc("Sales Order", result["sales_order"])
		self.assertEqual((station.sales_order, so.sp_station, so.sp_case), (so.name, station.name, self.case))
		self.assertEqual(so.project, station.project)
		self.assertEqual({r.project for r in so.items}, {station.project})
		self.assertEqual(flt(station.agreed_amount), flt(so.rounded_total or so.grand_total))
		dup = frappe.copy_doc(so)
		dup.sp_case = self.case
		with self.assertRaises(frappe.ValidationError):
			dup.insert()  # never a second order for the case

	def test_the_approved_option_b_becomes_the_order(self):
		approve_version(self.b.name)
		so = frappe.get_doc("Sales Order", self.contract()["sales_order"])
		self.assertEqual(so.items[0].prevdoc_docname, self.b.name)
		self.assertEqual(flt(so.items[0].rate), 120000)

	def test_warranty_years_come_from_the_approved_quote_lines(self):
		row = frappe.get_doc("Quotation", self.a.name).items[0]
		self.assertEqual(flt(row.sp_warranty_years), 5)
		approve_version(self.a.name)
		so = frappe.get_doc("Sales Order", self.contract()["sales_order"])
		self.assertEqual(flt(so.items[0].sp_warranty_years), 5)

	def test_needs_an_approved_version_and_the_projects_manager(self):
		with self.assertRaises(frappe.ValidationError):
			self.contract()  # nothing approved yet
		approve_version(self.a.name)
		other = make_user("sp.ct.other@example.com", ("customer_followup",))
		frappe.set_user(other)
		with self.assertRaises(frappe.PermissionError):
			make_contract(self.case)

	def test_the_contract_print_carries_the_quote_warranty_and_the_clauses(self):
		from unittest.mock import patch

		from smart_power.sp_core.documents import seed_contract_template
		from smart_power.sp_stations.contract_print import contract_print

		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		seed_contract_template()
		approve_version(self.a.name)
		so = frappe.get_doc("Sales Order", self.contract()["sales_order"])
		so.sp_referrer_commission = 4321
		so.append("sp_cheques", {"cheque_no": "778899", "due_date": so.transaction_date, "amount": 10000})
		so.save()
		data = contract_print(so)
		self.assertEqual(data.lines[0]["warranty_years"], 5)
		html = frappe.get_print("Sales Order", so.name, "SP Contract", doc=so)
		self.assertIn("sp-block-ownership", html)  # the admin's clauses
		self.assertIn("778899", html)  # the cheques annex
		for word in ("4321", "4,321", "sp_cost", "commission"):
			self.assertNotIn(word, html)
