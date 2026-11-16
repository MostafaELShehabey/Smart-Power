"""Consignment withdrawal by PO into company stock (SP-92; SP-91's and SP-28's last checks)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_stock import consignment
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_consignment import COMPANY, ITEM, SUPPLIER, ensure_supplier
from smart_power.tests.utils import make_quotation, make_user


def on_hand(warehouse: str) -> float:
	return flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": warehouse}, "actual_qty"))


def supplier_balance() -> float:
	rows = frappe.get_all(
		"GL Entry", {"party_type": "Supplier", "party": SUPPLIER, "is_cancelled": 0}, ["debit", "credit"]
	)
	return sum(flt(r.credit) - flt(r.debit) for r in rows)


class TestWithdraw(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_supplier()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		frappe.db.set_value("Item", ITEM, "sp_watt", 715)
		self.buyer = make_user("sp.wd.buyer@example.com", ("purchase_officer",))
		self.keeper = make_user("sp.wd.keeper@example.com", ("main_store_keeper",))
		self.main = wh.warehouse_of(COMPANY, wh.MAIN)
		self.doc = frappe.get_doc(
			{
				"doctype": "SP Consignment Container",
				"supplier": SUPPLIER,
				"item": ITEM,
				"company": COMPANY,
				"pallets": 18,
				"per_pallet": 33,
			}
		).insert()

	def tearDown(self):
		frappe.set_user("Administrator")

	def withdraw(self, qty, **kw):
		frappe.set_user(self.buyer)
		try:
			return consignment.withdraw(self.doc.name, qty, 8.25, **kw)
		finally:
			frappe.set_user("Administrator")

	def test_66_panels_at_8_25_per_watt_into_the_main_store(self):
		stock, owed = on_hand(self.main), supplier_balance()
		result = self.withdraw(66, warehouse=self.main)
		total = 66 * 715 * 8.25
		po = frappe.get_doc("Purchase Order", result["purchase_order"])
		self.assertEqual(
			(flt(po.grand_total), po.sp_is_consignment_conversion, po.sp_consignment_container),
			(total, 1, self.doc.name),
		)
		self.assertEqual(on_hand(self.main) - stock, 66)  # company stock +66 at the PO rate
		sle = frappe.get_all(
			"Stock Ledger Entry",
			{"voucher_no": result["purchase_receipt"], "is_cancelled": 0},
			["actual_qty", "incoming_rate"],
		)
		self.assertEqual((flt(sle[0].actual_qty), flt(sle[0].incoming_rate)), (66, 715 * 8.25))
		self.assertAlmostEqual(supplier_balance() - owed, total, places=2)  # the supplier balance
		self.doc.reload()
		self.assertEqual((self.doc.withdrawn_qty, self.doc.balance_qty), (66, 528))  # the container -66
		self.assertTrue(
			frappe.db.exists(
				"SP Review Item", {"reference_name": po.name, "category": "Consignment Conversion"}
			)
		)

	def test_for_a_station_its_project_carries_the_cost(self):
		quote = make_quotation(rate=50000, valid_days=3)
		quote.submit()
		frappe.db.set_value("SP Case", quote.sp_case, "accepted_quotation", quote.name)
		pm = make_user("sp.wd.pm@example.com", ("project_manager",))
		frappe.set_user(pm)
		station = frappe.get_doc(
			{"doctype": "SP Station", "case": quote.sp_case, "company": COMPANY}
		).insert()
		frappe.set_user("Administrator")
		station.reload()
		result = self.withdraw(10, station=station.name)
		site = wh.site_warehouse(station.project, create=False)
		self.assertEqual(on_hand(site), 10)
		lines = frappe.get_all(
			"GL Entry",
			{
				"voucher_no": ("in", [result["purchase_receipt"], result["purchase_invoice"]]),
				"is_cancelled": 0,
			},
			["project"],
		)
		self.assertTrue(lines)
		self.assertEqual({line.project for line in lines}, {station.project})

	def test_594_handed_over_and_withdrawn_leaves_nothing_and_only_246_in_stock(self):
		stock = on_hand(self.main)
		frappe.set_user(self.keeper)
		consignment.make_movement(self.doc.name, "Hand over", 348, customer_name="عملاء المورد")
		frappe.set_user("Administrator")
		self.withdraw(246, warehouse=self.main)
		self.doc.reload()
		self.assertEqual((self.doc.balance_qty, self.doc.status), (0, "Empty"))
		self.assertEqual(on_hand(self.main) - stock, 246)

	def test_more_than_available_or_without_the_right_role_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.withdraw(600, warehouse=self.main)
		self.assertFalse(frappe.db.exists("Purchase Order", {"sp_consignment_container": self.doc.name}))
		frappe.set_user(self.keeper)
		with self.assertRaises(frappe.PermissionError):
			consignment.withdraw(self.doc.name, 1, 8.25, warehouse=self.main)
