"""Financial centers (SP-27): five cost centers; a station is its project, never a cost center."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.sp_finance import centers
from smart_power.sp_finance.customer_payment import confirm
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import ensure_contract
from smart_power.sp_stations.station import record_write_off
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_customer_payment import PHOTO, account
from smart_power.tests.utils import (
	load_erpnext_test_data,
	make_quotation,
	make_user,
	set_setting,
	sign_contract,
)

load_erpnext_test_data()

COMPANY = "_Test Company"


class TestCenters(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		self.made = centers.seed_centers(COMPANY)
		set_setting(**{f"center_{key}": name for key, name in self.made.items()})
		self.projects = self.made[centers.PROJECTS]
		receivable = frappe.get_cached_value("Company", COMPANY, "default_receivable_account")
		set_setting(
			large_payment_threshold=100000,
			account_map=[
				{
					"event": "Write-off",
					"debit_account": "_Test Write Off - _TC",
					"debit_center_rule": "From document",
					"credit_account": receivable,
					"credit_center_rule": "From document",
					"project_rule": "Both sides",
				}
			],
		)
		self.admin = make_user("sp.cc.admin@example.com", ("admin",))
		self.amira = make_user("sp.cc.amira@example.com", ("project_manager", "collection_officer"))
		self.instapay = account("SP InstaPay", "Bank", "Official", account_type="Bank")
		q = make_quotation(rate=50000, valid_days=3, save=False)
		q.insert()
		q.set(
			"payment_schedule",
			[{"due_date": add_days(today(), 30), "invoice_portion": 100, "payment_amount": 50000}],
		)
		q.save()
		q.submit()
		approve_version(q.name)
		result = ensure_contract(q.sp_case)
		sign_contract(result["sales_order"])
		self.station = frappe.get_doc("SP Station", result["station"])

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_five_centers_under_the_company_group(self):
		root = frappe.db.get_value(
			"Cost Center", {"company": COMPANY, "is_group": 1}, "name", order_by="lft asc"
		)
		names = {frappe.db.get_value("Cost Center", n, "cost_center_name") for n in self.made.values()}
		self.assertEqual(names, {"Projects", "Showroom", "Winch", "Jumbo", "Indirect Pool"})
		self.assertEqual(
			{frappe.db.get_value("Cost Center", n, "parent_cost_center") for n in self.made.values()}, {root}
		)
		self.assertEqual(centers.seed_centers(COMPANY), self.made)  # once

	def test_the_station_is_its_project_tagged_projects(self):
		project = frappe.db.get_value(
			"Project", self.station.project, ["sp_station", "cost_center"], as_dict=True
		)
		self.assertEqual((project.sp_station, project.cost_center), (self.station.name, self.projects))
		self.assertFalse(
			frappe.db.exists("Cost Center", {"cost_center_name": self.station.name})
		)  # never a center

	def test_station_gl_lines_carry_projects_and_its_project(self):
		frappe.set_user(self.amira)
		payment = frappe.get_doc(
			{
				"doctype": "SP Customer Payment",
				"station": self.station.name,
				"amount": 10000,
				"method": "Payment Method-INSTAPAY",
				"receiving_account": self.instapay,
				"reference_no": "REF",
				"receipt_photo": PHOTO,
			}
		).insert()
		payment.submit()
		frappe.set_user(self.admin)
		entry = confirm(payment.name)
		frappe.set_user("Administrator")
		result = record_write_off(self.station.name, 1000, "تسوية")
		vouchers = [entry, result["journal_entry"]]
		lines = frappe.get_all(
			"GL Entry",
			{"voucher_no": ("in", vouchers), "is_cancelled": 0},
			["voucher_no", "cost_center", "project"],
		)
		self.assertTrue(lines)
		self.assertEqual(
			{(line.cost_center, line.project) for line in lines}, {(self.projects, self.station.project)}
		)
		# the General Ledger filtered by the station's project shows both
		by_project = set(
			frappe.get_all(
				"GL Entry", {"project": self.station.project, "is_cancelled": 0}, pluck="voucher_no"
			)
		)
		self.assertTrue(set(vouchers) <= by_project)

	def test_a_center_of_another_company_falls_back_to_its_default(self):
		self.assertEqual(
			centers.station_center("_Test Company 1"),
			frappe.get_cached_value("Company", "_Test Company 1", "cost_center"),
		)
