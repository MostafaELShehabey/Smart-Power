"""Receive goods (SP-84): the deliveries expected at my destinations, recorded with the exit permit
and a signature, waiting for confirmation with stock unchanged and no price in sight."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_stock import goods_receipt as gr
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock.purchase_orders import MAIN_STORE, SITE_DELIVERY, enable_batches
from smart_power.tests.test_purchase_orders import COMPANY, ITEM, order, row, station
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

PHOTO, SIGNATURE = "/private/files/exit-permit.jpg", "data:image/png;base64,iVBORw0KGgo="


class TestGoodsReceipt(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		enable_batches()
		cls.receiver = make_user("sp.gr.mostafa@example.com", ("site_receiver",))
		cls.other = make_user("sp.gr.other@example.com", ("site_receiver",))
		cls.keeper = make_user("sp.gr.keeper@example.com", ("main_store_keeper",))
		cls.confirmer = make_user("sp.gr.aya@example.com", ("receipt_confirmer",))

	def tearDown(self):
		frappe.set_user("Administrator")

	def site_order(self, qty=40):
		st = station()
		frappe.db.set_value("SP Station", st.name, "site_receiver", self.receiver)
		po = order([row(qty=qty)], sp_station=st.name, sp_destination_type=SITE_DELIVERY).insert()
		po.submit()
		return po

	def card(self, po):
		return next((c for c in gr.expected_deliveries() if c["purchase_order"] == po.name), None)

	def record(self, po, lines, **kw):
		values = {"exit_permit_photo": PHOTO, "signature": SIGNATURE, **kw}
		rows = [
			{"purchase_order_item": po.items[0].name, "received_qty": q, "condition": c} for q, c in lines
		]
		return gr.record_receipt(po.name, po.items[0].warehouse, rows, **values)

	def test_the_receiver_sees_what_is_expected(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		line = self.card(po)["lines"][0]
		self.assertEqual((line["ordered"], line["received"], line["remaining"]), (40, 0, 40))

	def test_no_price_reaches_the_receiver(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		text = frappe.as_json(self.card(po))
		for word in ("rate", "amount", "price", "5100"):
			self.assertNotIn(word, text)

	def test_38_good_and_2_damaged_wait_for_confirmation_with_stock_unchanged(self):
		po = self.site_order()
		warehouse = po.items[0].warehouse
		before = flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": warehouse}, "actual_qty"))
		frappe.set_user(self.receiver)
		result = self.record(po, [(38, "OK"), (2, "Damaged")])
		frappe.set_user("Administrator")
		self.assertEqual(result["status"], "Pending confirmation")
		doc = frappe.get_doc(gr.RECEIPT, result["name"])
		self.assertEqual((doc.status, doc.received_by), ("Pending confirmation", self.receiver))
		self.assertEqual([(r.received_qty, r.condition) for r in doc.lines], [(38, "OK"), (2, "Damaged")])
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{
					"task_type": gr.TASK_TYPE,
					"reference_name": doc.name,
					"assigned_to": self.confirmer,
					"status": "Open",
				},
			)
		)
		after = flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": warehouse}, "actual_qty"))
		self.assertEqual(after, before)
		self.assertEqual(flt(frappe.db.get_value("Purchase Order", po.name, "per_received")), 0)
		self.assertFalse(frappe.db.exists("Purchase Receipt Item", {"purchase_order": po.name}))

	def test_the_confirmer_can_open_the_exit_permit(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		photo = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"permit-{frappe.generate_hash(length=6)}.png",
				"content": b"permit",
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		name = self.record(po, [(40, "OK")], exit_permit_photo=photo.file_url)["name"]
		frappe.set_user(self.confirmer)
		photo.reload()
		self.assertEqual((photo.attached_to_doctype, photo.attached_to_name), (gr.RECEIPT, name))
		self.assertTrue(photo.has_permission("read"))
		frappe.set_user(self.other)
		self.assertFalse(photo.has_permission("read"))

	def test_someone_elses_file_is_not_taken_over(self):
		po = self.site_order()
		theirs = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"theirs-{frappe.generate_hash(length=6)}.png",
				"content": b"theirs",
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.receiver)
		self.record(po, [(40, "OK")], exit_permit_photo=theirs.file_url)
		frappe.set_user("Administrator")
		theirs.reload()
		self.assertFalse(theirs.attached_to_name)

	def test_a_receipt_needs_the_exit_permit_and_a_signature(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		with self.assertRaises(frappe.MandatoryError):
			self.record(po, [(40, "OK")], exit_permit_photo=None)
		with self.assertRaises(frappe.MandatoryError):
			self.record(po, [(40, "OK")], signature=None)

	def test_what_waits_counts_as_received(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		self.record(po, [(30, "OK")])
		line = self.card(po)["lines"][0]
		self.assertEqual((line["received"], line["remaining"]), (30, 10))
		with self.assertRaises(frappe.ValidationError):
			self.record(po, [(11, "OK")])
		self.record(po, [(10, "Short")])
		self.assertIsNone(self.card(po))

	def test_a_rejected_receipt_frees_its_quantity(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		name = self.record(po, [(40, "OK")])["name"]
		frappe.set_user("Administrator")
		frappe.db.set_value(gr.RECEIPT, name, {"status": gr.REJECTED, "reject_reason": "الصورة غير واضحة"})
		frappe.set_user(self.receiver)
		self.assertEqual(self.card(po)["lines"][0]["remaining"], 40)
		mine = next(r for r in gr.my_receipts() if r.name == name)
		self.assertEqual(mine.reject_reason, "الصورة غير واضحة")

	def test_a_stations_named_receiver_is_the_only_one(self):
		po = self.site_order()
		frappe.set_user(self.other)
		self.assertIsNone(self.card(po))
		with self.assertRaises(frappe.PermissionError):
			self.record(po, [(40, "OK")])

	def test_the_main_store_keeper_receives_at_the_main_store(self):
		po = order([row(qty=5)], sp_destination_type=MAIN_STORE).insert()
		po.submit()
		frappe.set_user(self.keeper)
		self.assertTrue(self.card(po))
		frappe.set_user(self.receiver)
		self.assertIsNone(self.card(po))

	def test_a_responsible_user_takes_over_the_store(self):
		po = order([row(qty=5)], sp_destination_type=MAIN_STORE).insert()
		po.submit()
		frappe.db.set_value("Warehouse", po.items[0].warehouse, "sp_responsible_user", self.other)
		self.addCleanup(frappe.db.set_value, "Warehouse", po.items[0].warehouse, "sp_responsible_user", None)
		frappe.set_user(self.keeper)
		self.assertIsNone(self.card(po))
		frappe.set_user(self.other)
		self.assertTrue(self.card(po))

	def test_a_recorded_receipt_cannot_be_changed(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		name = self.record(po, [(40, "OK")])["name"]
		frappe.set_user("Administrator")
		doc = frappe.get_doc(gr.RECEIPT, name)
		doc.lines[0].received_qty = 1
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_a_receiver_sees_only_their_own_receipts(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		name = self.record(po, [(40, "OK")])["name"]
		frappe.set_user(self.other)
		self.assertNotIn(name, frappe.get_list(gr.RECEIPT, pluck="name"))
		frappe.set_user(self.confirmer)
		self.assertIn(name, frappe.get_list(gr.RECEIPT, pluck="name"))
