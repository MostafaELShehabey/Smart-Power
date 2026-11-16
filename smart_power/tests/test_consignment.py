"""Africa System consignment by quantity, outside the stock ledger (SP-91; SP-28's first check)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_stock import consignment
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
SUPPLIER = "_Test SP Africa System"
ITEM = "_Test Item"


def stock_value() -> float:
	rows = frappe.get_all(
		"Stock Ledger Entry", {"is_cancelled": 0, "company": COMPANY}, ["stock_value_difference"]
	)
	return sum(flt(r.stock_value_difference) for r in rows)


class TestConsignment(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)
		if not frappe.db.exists("Supplier", SUPPLIER):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": SUPPLIER,
					"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}),
					"sp_is_consignment_owner": 1,
				}
			).insert()

	def setUp(self):
		set_setting(consignment_low_balance=33)
		self.keeper = make_user("sp.cn.keeper@example.com", ("main_store_keeper",))
		self.admin = make_user("sp.cn.admin@example.com", ("admin",))

	def tearDown(self):
		frappe.set_user("Administrator")

	def container(self, pallets=18, per_pallet=33):
		frappe.set_user(self.keeper)
		try:
			return frappe.get_doc(
				{
					"doctype": "SP Consignment Container",
					"supplier": SUPPLIER,
					"item": ITEM,
					"company": COMPANY,
					"container_no": "AS-594",
					"pallets": pallets,
					"per_pallet": per_pallet,
				}
			).insert()
		finally:
			frappe.set_user("Administrator")

	def move(self, doc, kind, qty, **kw):
		frappe.set_user(self.keeper)
		try:
			return consignment.make_movement(doc.name, kind, qty, **kw)
		finally:
			frappe.set_user("Administrator")

	def test_594_on_consignment_add_no_stock_and_no_ledger(self):
		sle, gl, value = frappe.db.count("Stock Ledger Entry"), frappe.db.count("GL Entry"), stock_value()
		doc = self.container()
		self.assertEqual(
			(doc.received_qty, doc.balance_qty, doc.available_qty, doc.status), (594, 594, 594, "Open")
		)
		self.assertEqual((frappe.db.count("Stock Ledger Entry"), frappe.db.count("GL Entry")), (sle, gl))
		self.assertEqual(stock_value(), value)

	def test_reservation_hand_over_and_return(self):
		doc = self.container()
		res = self.move(doc, "Reserve", 100, customer_name="أحمد محمود")
		doc.reload()
		self.assertEqual((doc.balance_qty, doc.reserved_qty, doc.available_qty), (594, 100, 494))
		with self.assertRaises(frappe.ValidationError):
			self.move(doc, "Return to supplier", 495)  # more than is available
		self.move(doc, "Hand over", 100, customer_name="أحمد محمود", reservation=res)
		self.assertEqual(frappe.db.get_value("SP Consignment Movement", res, "status"), "Cleared")
		self.move(doc, "Hand over", 248, customer_name="محمد علي")
		self.move(doc, "Return to supplier", 10)
		doc.reload()
		self.assertEqual(
			(doc.handed_over_qty, doc.returned_qty, doc.reserved_qty, doc.balance_qty, doc.available_qty),
			(348, 10, 0, 236, 236),
		)

	def test_cancelling_a_hand_over_reopens_its_reservation(self):
		doc = self.container()
		res = self.move(doc, "Reserve", 50, customer_name="عميل")
		hand = self.move(doc, "Hand over", 50, customer_name="عميل", reservation=res)
		frappe.get_doc("SP Consignment Movement", hand).cancel()
		self.assertEqual(
			frappe.db.get_value("SP Consignment Movement", res, ["status", "cleared_qty"]), ("Open", 0)
		)
		doc.reload()
		self.assertEqual((doc.balance_qty, doc.reserved_qty), (594, 50))

	def test_low_balance_alerts_once(self):
		doc = self.container(pallets=2, per_pallet=33)
		self.move(doc, "Hand over", 30, customer_name="عميل")
		self.move(doc, "Hand over", 5, customer_name="عميل")
		doc.reload()
		self.assertEqual((doc.balance_qty, doc.status), (31, "Low"))
		self.assertEqual(
			frappe.db.count(
				"Notification Log",
				{"document_name": doc.name, "sp_event": "consignment_low", "for_user": self.keeper},
			),
			1,
		)

	def test_withdrawing_is_only_by_po(self):
		doc = self.container()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "SP Consignment Movement",
					"container": doc.name,
					"movement_type": "Withdraw by PO",
					"qty": 5,
				}
			).insert()

	def test_the_storage_fee_is_income_off_the_suppliers_balance(self):
		doc = self.container()
		frappe.set_user(self.admin)
		je = consignment.record_fee(doc.name, 1500, consignment.DEDUCTED)
		frappe.set_user("Administrator")
		rows = {r.account: r for r in frappe.get_doc("Journal Entry", je).accounts}
		income = frappe.db.get_value("Account", {"company": COMPANY, "account_name": "Storage Fees"})
		self.assertEqual(flt(rows[income].credit_in_account_currency), 1500)
		payable = next(r for r in rows.values() if r.party == SUPPLIER)
		self.assertEqual(flt(payable.debit_in_account_currency), 1500)
		self.assertEqual(len(frappe.get_doc("SP Consignment Container", doc.name).fees), 1)
		frappe.set_user(self.keeper)
		with self.assertRaises(frappe.PermissionError):
			consignment.record_fee(doc.name, 10, consignment.DEDUCTED)

	def test_only_a_consignment_owner_supplier(self):
		other = frappe.db.get_value("Supplier", {"sp_is_consignment_owner": 0})
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "SP Consignment Container",
					"supplier": other,
					"item": ITEM,
					"pallets": 1,
					"per_pallet": 1,
				}
			).insert()
