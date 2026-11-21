"""R1 Station financial position (SP-139): each column against hand-calculated figures."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, getdate, today

from smart_power.sp_finance.report.sp_station_position.sp_station_position import execute
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_purchase_orders import COMPANY, SUPPLIER
from smart_power.tests.test_station import receive
from smart_power.tests.test_supplier_ledger import invoice
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, sign_contract

load_erpnext_test_data()

STATION = "SP Station"
AGRI = "Financing Type-AGRI"


class TestStationPosition(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		cls.admin = make_user("sp.r1.admin@example.com", ("admin",))
		cls.amira = make_user("sp.r1.amira@example.com", ("project_manager",))

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def station(self, rate, paid=0, estimated=0, financing=None):
		quote = make_quotation(rate=rate, valid_days=3)
		quote.submit()
		approve_version(quote.name)
		result = make_contract(quote.sp_case)
		sign_contract(result["sales_order"])
		doc = frappe.get_doc(STATION, result["station"])
		values = {"estimated_cost_snapshot": json.dumps({"total_cost": estimated})}
		if financing and frappe.db.exists("SP List Value", financing):
			values["financing_type"] = financing
		frappe.db.set_value(STATION, doc.name, values)
		if paid:
			receive(doc, paid)
		return frappe.get_doc(STATION, doc.name)

	def supplier_invoice(self, station, amount, paid=0):
		"""A supplier's invoice charged to the station (the supplier ledger tests' own), partly paid."""
		pi = invoice([(station.project, amount)], SUPPLIER)
		if paid:
			from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

			pe = get_payment_entry("Purchase Invoice", pi.name, party_amount=paid)
			pe.reference_no, pe.reference_date = "SP139", today()
			pe.paid_from = "_Test Cash - _TC"
			pe.insert()
			pe.submit()
		return pi

	def report(self, **filters):
		frappe.set_user(self.admin)
		try:
			_columns, data = execute({"year": getdate(today()).year, **filters})
		finally:
			frappe.set_user("Administrator")
		return {row["station"]: row for row in data}

	def test_three_stations_match_the_hand_calculated_figures(self):
		a = self.station(20000, paid=15000, estimated=12000)
		self.supplier_invoice(a, 10000, paid=6000)
		b = self.station(30000)
		c = self.station(50000, paid=50000, estimated=35000)
		self.supplier_invoice(c, 30000, paid=30000)
		rows = self.report()
		expected = {
			a.name: {
				"agreed": 20000, "estimated_cost": 12000, "actual_cost": 10000,
				"owed_to_suppliers": 10000, "paid_to_suppliers": 6000, "remaining_to_suppliers": 4000,
				"collected": 15000, "cash_position": 5000, "remaining_from_customer": 5000,
				"expected_profit": 8000, "profit": 10000,
			},
			b.name: {
				"agreed": 30000, "estimated_cost": 0, "actual_cost": 0,
				"owed_to_suppliers": 0, "paid_to_suppliers": 0, "remaining_to_suppliers": 0,
				"collected": 0, "cash_position": 0, "remaining_from_customer": 30000,
				"expected_profit": 30000, "profit": 30000,
			},
			c.name: {
				"agreed": 50000, "estimated_cost": 35000, "actual_cost": 30000,
				"owed_to_suppliers": 30000, "paid_to_suppliers": 30000, "remaining_to_suppliers": 0,
				"collected": 50000, "cash_position": 20000, "remaining_from_customer": 0,
				"expected_profit": 15000, "profit": 20000,
			},
		}  # fmt: skip
		for station, figures in expected.items():
			got = {key: flt(rows[station][key]) for key in figures}
			self.assertEqual(got, {k: flt(v) for k, v in figures.items()}, station)

	def test_the_financing_filter_shows_only_those_stations_and_the_totals_follow(self):
		if not frappe.db.exists("SP List Value", AGRI):
			self.skipTest("no Agri Bank financing value on this site")
		agri = self.station(40000, financing=AGRI)
		other = self.station(25000)
		rows = self.report(financing=AGRI)
		self.assertIn(agri.name, rows)
		self.assertNotIn(other.name, rows)
		label = frappe.db.get_value("SP List Value", AGRI, "value_ar") or AGRI
		self.assertEqual({r["financing"] for r in rows.values()}, {label})  # the totals row sums these only

	def test_only_the_admin_opens_it(self):
		frappe.set_user(self.amira)
		try:
			with self.assertRaises(frappe.PermissionError):
				execute({})
		finally:
			frappe.set_user("Administrator")

	def test_the_columns_follow_the_owners_sheet(self):
		columns, _data = execute({})
		self.assertEqual(
			[c["fieldname"] for c in columns][:7],
			["station", "customer_name", "contract_date", "financing", "capacity_kw", "status", "agreed"],
		)
