"""Receipt confirmation (SP-85): confirming posts stock and the supplier's payable, a discrepancy
posts the good quantity and leaves the rest open, and a rejection posts nothing."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_finance.centers import PROJECTS, center, seed_centers
from smart_power.sp_stock import goods_receipt as gr
from smart_power.sp_stock import receipt_confirmation as rc
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock.purchase_orders import SITE_DELIVERY, enable_batches
from smart_power.tests.test_goods_receipt import GROUP, SIGNATURE, photo
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_purchase_orders import COMPANY, order, row, station
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

RATE = 100
REASON = "الكمية لا تطابق إذن الخروج"
PERPETUAL = {
	"enable_perpetual_inventory": 1,
	"stock_received_but_not_billed": "Stock Received But Not Billed - _TC",
	"default_inventory_account": "Stock In Hand - _TC",
}


class TestReceiptConfirmation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_centers(COMPANY)
		enable_batches()
		frappe.db.set_value("Company", COMPANY, PERPETUAL)
		cls.forget_perpetual_setting()
		cls.receiver = make_user("sp.rc.mostafa@example.com", ("site_receiver",))
		cls.confirmer = make_user("sp.rc.aya@example.com", ("receipt_confirmer",))
		cls.buyer = make_user("sp.rc.amira@example.com", ("purchase_officer",))

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		cls.forget_perpetual_setting()

	@staticmethod
	def forget_perpetual_setting():
		"""ERPNext keeps this per company for the whole process, so other tests' value would stay."""
		frappe.clear_document_cache("Company", COMPANY)
		getattr(frappe.local, "enable_perpetual_inventory", {}).pop(COMPANY, None)

	def tearDown(self):
		frappe.set_user("Administrator")

	def site_order(self, qty=40, item=None):
		st = station()
		frappe.db.set_value("SP Station", st.name, "site_receiver", self.receiver)
		values = {"qty": qty, "rate": RATE}
		if item:
			values["item_code"] = item
		po = order([row(**values)], sp_station=st.name, sp_destination_type=SITE_DELIVERY).insert()
		po.submit()
		return po

	def record(self, po, lines):
		frappe.set_user(self.receiver)
		rows = [
			{"purchase_order_item": po.items[0].name, "received_qty": q, "condition": c, **extra}
			for q, c, extra in lines
		]
		name = gr.record_receipt(po.name, po.items[0].warehouse, rows, photo(), SIGNATURE)["name"]
		frappe.set_user(self.confirmer)
		return name

	def received(self, po):
		return flt(frappe.db.get_value("Purchase Order Item", po.items[0].name, "received_qty"))

	def invoice_of(self, receipt):
		return frappe.get_doc(
			"Purchase Invoice",
			frappe.db.get_value("Purchase Invoice Item", {"purchase_receipt": receipt}, "parent"),
		)

	def test_confirming_posts_stock_and_the_supplier_payable(self):
		po = self.site_order()
		name = self.record(po, [(40, "OK", {})])
		result = rc.confirm_receipt(name)
		doc = frappe.get_doc(gr.RECEIPT, name)
		self.assertEqual((doc.docstatus, doc.sp_receipt_status), (1, gr.CONFIRMED))
		self.assertEqual(doc.sp_confirmed_by, self.confirmer)
		self.assertEqual(frappe.session.user, self.confirmer)
		self.assertEqual(self.received(po), 40)
		self.assertEqual(
			flt(
				frappe.db.get_value(
					"Bin",
					{"warehouse": po.items[0].warehouse, "item_code": po.items[0].item_code},
					"actual_qty",
				)
			),
			40,
		)
		invoice = frappe.get_doc("Purchase Invoice", result["purchase_invoice"])
		self.assertEqual((invoice.docstatus, flt(invoice.grand_total)), (1, 40 * RATE))
		self.assertEqual(invoice.bill_no, f"{po.name}-1")
		self.assertFalse(
			frappe.db.exists("SP Task", {"reference_name": name, "task_type": gr.TASK_TYPE, "status": "Open"})
		)

	def test_38_of_40_posts_38_and_leaves_2_on_the_order(self):
		po = self.site_order()
		name = self.record(po, [(38, "OK", {}), (2, "Damaged", {})])
		rc.mark_discrepancy(name, "لوحان مكسوران")
		doc = frappe.get_doc(gr.RECEIPT, name)
		self.assertEqual((doc.docstatus, doc.sp_receipt_status), (1, gr.DISCREPANCY))
		self.assertEqual([flt(r.qty) for r in doc.items], [38])
		self.assertIn("لوحان مكسوران", doc.sp_discrepancy_notes)
		self.assertIn("2 x", doc.sp_discrepancy_notes)
		self.assertEqual(self.received(po), 38)
		self.assertEqual(flt(self.invoice_of(name).grand_total), 38 * RATE)
		frappe.set_user(self.receiver)
		line = next(c for c in gr.expected_deliveries() if c["purchase_order"] == po.name)["lines"][0]
		self.assertEqual(line["remaining"], 2)
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Notification Log", {"for_user": self.buyer, "document_name": name}))

	def test_a_rejection_posts_nothing_and_goes_back_with_the_reason(self):
		po = self.site_order()
		name = self.record(po, [(40, "OK", {})])
		rc.reject_receipt(name, REASON)
		doc = frappe.get_doc(gr.RECEIPT, name)
		self.assertEqual(
			(doc.docstatus, doc.sp_receipt_status, doc.sp_reject_reason), (0, gr.REJECTED, REASON)
		)
		self.assertFalse(frappe.db.exists("Stock Ledger Entry", {"voucher_no": name}))
		self.assertFalse(frappe.db.exists("Purchase Invoice Item", {"purchase_receipt": name}))
		task = {
			"reference_name": name,
			"task_type": gr.REJECT_TASK,
			"assigned_to": self.receiver,
			"status": "Open",
		}
		self.assertEqual(frappe.db.get_value("SP Task", task, "description"), REASON)
		again = self.record(po, [(40, "OK", {})])  # the receiver can record it again
		self.assertNotEqual(again, name)
		self.assertFalse(frappe.db.exists("SP Task", task))

	def test_the_ledger_carries_the_station_and_the_projects_center(self):
		po = self.site_order()
		name = self.record(po, [(40, "OK", {})])
		invoice = rc.confirm_receipt(name)["purchase_invoice"]
		frappe.set_user("Administrator")
		project = po.items[0].project
		self.assertTrue(project)
		for voucher in (name, invoice):
			entries = frappe.get_all(
				"GL Entry", {"voucher_no": voucher, "is_cancelled": 0}, ["project", "cost_center"]
			)
			self.assertTrue(entries)
			for entry in entries:
				self.assertEqual((entry.project, entry.cost_center), (project, center(PROJECTS, COMPANY)))

	def test_a_damaged_receipt_cannot_be_confirmed_whole(self):
		po = self.site_order()
		name = self.record(po, [(38, "OK", {}), (2, "Damaged", {})])
		self.assertRaises(frappe.ValidationError, rc.confirm_receipt, name)
		self.assertRaises(frappe.ValidationError, rc.mark_discrepancy, name, "  ")
		self.assertRaises(frappe.ValidationError, rc.reject_receipt, name, " ")
		self.assertEqual(frappe.db.get_value(gr.RECEIPT, name, "docstatus"), 0)

	def test_all_damaged_is_a_rejection(self):
		po = self.site_order()
		name = self.record(po, [(40, "Damaged", {})])
		self.assertRaises(frappe.ValidationError, rc.mark_discrepancy, name, "كله مكسور")

	def test_only_the_technical_office_confirms(self):
		po = self.site_order()
		name = self.record(po, [(40, "OK", {})])
		frappe.set_user(self.receiver)
		for action in (rc.confirm_receipt, rc.pending_receipts):
			args = (name,) if action is rc.confirm_receipt else ()
			self.assertRaises(frappe.PermissionError, action, *args)

	def test_a_receipt_is_decided_once(self):
		po = self.site_order()
		name = self.record(po, [(40, "OK", {})])
		rc.confirm_receipt(name)
		self.assertRaises(frappe.ValidationError, rc.reject_receipt, name, REASON)
		self.assertEqual(frappe.db.count("Purchase Invoice Item", {"purchase_receipt": name}), 1)

	def test_a_serial_item_is_received_with_its_serial(self):
		frappe.set_user("Administrator")
		code = make_item("SP-RC-MOTOR", item_group=GROUP, has_serial_no=1, is_stock_item=1).name
		po = self.site_order(qty=1, item=code)
		frappe.set_user(self.receiver)
		nameplate = photo()
		name = self.record(po, [(1, "OK", {"serial_no": "SP-RC-0001", "serial_photo": nameplate})])
		rc.confirm_receipt(name)
		self.assertEqual(frappe.db.get_value("Serial No", "SP-RC-0001", "warehouse"), po.items[0].warehouse)

	def test_a_reserved_line_stays_reserved_once_received(self):
		st = station()
		frappe.db.set_value("SP Station", st.name, "site_receiver", self.receiver)
		so = frappe.get_doc("Sales Order", st.sales_order)
		if so.docstatus == 0:
			so.submit()
		line = so.items[0]
		frappe.db.set_value("Sales Order Item", line.name, "reserve_stock", 1)
		values = {"qty": line.qty, "rate": RATE, "item_code": line.item_code}
		values.update({"sales_order": so.name, "sales_order_item": line.name})
		po = order([row(**values)], sp_station=st.name, sp_destination_type=SITE_DELIVERY).insert()
		po.submit()
		name = self.record(po, [(line.qty, "OK", {})])
		rc.confirm_receipt(name)
		reserved = frappe.db.get_value(
			"Stock Reservation Entry",
			{"voucher_detail_no": line.name, "from_voucher_no": name, "docstatus": 1},
			["reserved_qty", "warehouse"],
			as_dict=True,
		)
		self.assertEqual(
			(flt(reserved.reserved_qty), reserved.warehouse), (flt(line.stock_qty), po.items[0].warehouse)
		)

	def test_a_draft_sales_order_does_not_hold_up_the_confirmation(self):
		st = station()
		frappe.db.set_value("SP Station", st.name, "site_receiver", self.receiver)
		so = frappe.get_doc("Sales Order", st.sales_order)
		if so.docstatus != 0:
			self.skipTest("the contract submitted this order")
		line = so.items[0]
		frappe.db.set_value("Sales Order Item", line.name, "reserve_stock", 1)
		values = {"qty": line.qty, "rate": RATE, "item_code": line.item_code}
		values.update({"sales_order": so.name, "sales_order_item": line.name})
		po = order([row(**values)], sp_station=st.name, sp_destination_type=SITE_DELIVERY).insert()
		po.submit()
		name = self.record(po, [(line.qty, "OK", {})])
		rc.confirm_receipt(name)
		self.assertEqual(frappe.db.get_value(gr.RECEIPT, name, "docstatus"), 1)
		self.assertFalse(frappe.db.exists("Stock Reservation Entry", {"from_voucher_no": name}))

	def test_the_confirmer_sees_the_lines_without_a_price(self):
		po = self.site_order()
		name = self.record(po, [(38, "OK", {}), (2, "Damaged", {})])
		card = next(r for r in rc.pending_receipts() if r.name == name)
		self.assertEqual((card.purchase_order, card.received_by), (po.name, self.receiver))
		self.assertTrue(card.exit_permit)
		self.assertEqual(
			[(l.ordered, l.received_qty, l.condition) for l in card.lines],
			[(40, 38, "OK"), (40, 2, "Damaged")],
		)
		for key in ("rate", "amount", "base_rate", "grand_total"):
			self.assertNotIn(key, card)
			self.assertNotIn(key, card.lines[0])
