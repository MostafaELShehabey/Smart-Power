"""The confirmed deposit turns the approved quote into a station (SP-175)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_sales.quotation import approve_version, new_version
from smart_power.sp_stations.deposit import run_deposit
from smart_power.sp_stations.setup import enable_stock_reservation
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user

load_erpnext_test_data()

COMPANY, ITEM, SUPPLIER = "_Test Company", "_Test Item", "_Test Supplier"


def deposit(case, customer, amount=50000, submit=True):
	pe = frappe.get_doc(
		{
			"doctype": "Payment Entry",
			"payment_type": "Receive",
			"company": COMPANY,
			"party_type": "Customer",
			"party": customer,
			"paid_from": "_Test Receivable - _TC",
			"paid_to": "_Test Cash - _TC",
			"paid_amount": amount,
			"received_amount": amount,
			"reference_no": "DEP",
			"reference_date": today(),
			"sp_is_deposit": 1,
			"sp_case": case,
		}
	).insert()
	if submit:
		pe.submit()
	return pe


class TestDeposit(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		enable_stock_reservation()
		cls.main = wh.warehouse_of(COMPANY, wh.MAIN)
		item = frappe.get_doc("Item", ITEM)
		if not any(d.company == COMPANY for d in item.item_defaults):
			item.append("item_defaults", {"company": COMPANY})
		for d in item.item_defaults:
			if d.company == COMPANY:
				d.default_supplier = SUPPLIER
		item.save()

	def setUp(self):
		self.amira = make_user("sp.dp.amira@example.com", ("project_manager", "contract_manager"))
		self.admin = make_user("sp.dp.admin@example.com", ("admin",))
		# one in the main store; the quote asks for three
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": COMPANY,
				"items": [{"item_code": ITEM, "qty": 1, "t_warehouse": self.main, "basic_rate": 100}],
			}
		).insert()
		se.submit()
		self.v1 = make_quotation(rate=100000, valid_days=3, save=False)
		self.v1.items[0].qty = 3
		self.v1.insert()
		self.v1.submit()
		self.v2 = frappe.get_doc("Quotation", new_version(self.v1.name))
		self.v2.submit()
		approve_version(self.v2.name)
		self.case = self.v1.sp_case
		self.customer = self.v1.party_name

	def so_of(self):
		return frappe.db.get_value("Sales Order", {"sp_case": self.case, "docstatus": 1})

	def counts(self, so, station):
		return (
			frappe.db.count("Sales Order", {"sp_case": self.case, "docstatus": ("<", 2)}),
			frappe.db.count("SP Station", {"case": self.case}),
			frappe.db.count("Purchase Order Item", {"sales_order": so, "docstatus": 0}),
			frappe.db.count("Stock Reservation Entry", {"voucher_no": so, "docstatus": 1}),
			frappe.db.count("SP Task", {"reference_name": station, "task_type": "Technical Review"}),
		)

	def test_a_confirmed_deposit_on_v2_makes_everything_linked(self):
		pe = deposit(self.case, self.customer)
		so = frappe.get_doc("Sales Order", self.so_of())
		station = frappe.get_doc("SP Station", so.sp_station)
		self.assertEqual(so.items[0].prevdoc_docname, self.v2.name)  # from the approved version
		self.assertEqual((station.sales_order, so.project), (so.name, station.project))
		self.assertTrue(station.execution_owner)  # the projects manager, though the admin confirmed
		self.assertTrue(so.sp_estimate_frozen_on)
		self.assertEqual(so.sp_deposit_payment, pe.name)
		self.assertEqual(self.counts(so.name, station.name), (1, 1, 1, 1, 1))
		po = frappe.get_doc(
			"Purchase Order",
			frappe.db.get_value("Purchase Order Item", {"sales_order": so.name}, "parent"),
		)
		self.assertEqual((po.supplier, po.sp_source, po.docstatus), (SUPPLIER, "Deposit", 0))
		self.assertEqual(flt(po.items[0].qty), 2)  # three asked, one in stock
		sre = frappe.get_doc("Stock Reservation Entry", {"voucher_no": so.name, "docstatus": 1})
		self.assertEqual(flt(sre.reserved_qty), 1)
		# the deposit is the order's advance and the station's paid money
		pe.reload()
		self.assertEqual(
			[(r.reference_doctype, r.reference_name) for r in pe.references], [("Sales Order", so.name)]
		)
		self.assertEqual(flt(frappe.db.get_value("SP Station", station.name, "paid_amount")), 50000)
		# statuses
		self.assertEqual(frappe.db.get_value("SP Case", self.case, "status"), "Won")
		self.assertEqual(frappe.db.get_value("Quotation", self.v2.name, "sp_status"), "Approved")
		self.assertEqual(frappe.db.get_value("Quotation", self.v1.name, "sp_status"), "Superseded")
		self.assertTrue(
			frappe.db.exists(
				"Notification Log", {"document_type": "SP Station", "document_name": station.name}
			)
		)

	def test_a_retry_duplicates_nothing(self):
		pe = deposit(self.case, self.customer)
		so = self.so_of()
		station = frappe.db.get_value("Sales Order", so, "sp_station")
		before = self.counts(so, station)
		run_deposit(pe.name)
		run_deposit(pe.name)
		self.assertEqual(self.counts(so, station), before)

	def test_a_rejected_deposit_makes_nothing(self):
		deposit(self.case, self.customer, submit=False)  # recorded, never confirmed
		self.assertIsNone(frappe.db.get_value("Sales Order", {"sp_case": self.case}))
		self.assertFalse(frappe.db.exists("SP Station", {"case": self.case}))
		self.assertNotEqual(frappe.db.get_value("SP Case", self.case, "status"), "Won")

	def test_a_plain_payment_is_no_deposit(self):
		pe = deposit(self.case, self.customer, submit=False)
		pe.sp_is_deposit = 0
		pe.save()
		pe.submit()
		self.assertIsNone(self.so_of())
