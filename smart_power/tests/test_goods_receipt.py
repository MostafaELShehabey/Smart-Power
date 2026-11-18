"""Receive goods (SP-84): the deliveries expected at my destinations, recorded on a draft Purchase
Receipt with the exit permit and a signature, waiting for confirmation with stock unchanged and no
price in sight."""

import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.permissions import COST_PERMLEVEL
from smart_power.sp_stock import goods_receipt as gr
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock.purchase_orders import MAIN_STORE, SITE_DELIVERY, enable_batches
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_purchase_orders import COMPANY, ITEM, order, row, station
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

GROUP = "_Test Item Group"
SIGNATURE = "data:image/png;base64,iVBORw0KGgo="


def photo() -> str:
	"""A private photo uploaded by whoever is signed in."""
	name = f"permit-{frappe.generate_hash(length=8)}.png"
	content = frappe.generate_hash(length=16).encode()
	doc = frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 1})
	return doc.insert(ignore_permissions=True).file_url


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
		values = {"exit_permit_photo": photo(), "signature": SIGNATURE, **kw}
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
		self.assertEqual(doc.docstatus, 0)
		self.assertEqual((doc.sp_receipt_status, doc.sp_received_by), ("Pending confirmation", self.receiver))
		self.assertEqual((doc.owner, doc.modified_by), (self.receiver, self.receiver))
		self.assertEqual([(r.received_qty, r.sp_condition) for r in doc.items], [(38, "OK"), (2, "Damaged")])
		self.assertEqual({r.rate for r in doc.items}, {5100})  # the order's price, kept for the confirmer
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
		self.assertFalse(frappe.db.exists("Stock Ledger Entry", {"voucher_no": doc.name}))

	def test_the_confirmer_can_open_the_exit_permit(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		url = photo()
		name = self.record(po, [(40, "OK")], exit_permit_photo=url)["name"]
		frappe.set_user(self.confirmer)
		attached = frappe.get_doc("File", {"file_url": url})
		self.assertEqual((attached.attached_to_doctype, attached.attached_to_name), (gr.RECEIPT, name))
		self.assertTrue(attached.has_permission("read"))

	def test_the_photos_stay_with_the_receipt(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		url = photo()
		name = self.record(po, [(40, "OK")], exit_permit_photo=url)["name"]
		file_name = frappe.db.get_value("File", {"file_url": url, "attached_to_name": name})
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("File", file_name, ignore_permissions=True)
		frappe.set_user("Administrator")
		frappe.delete_doc(gr.RECEIPT, name, ignore_permissions=True, force=True)
		self.assertFalse(frappe.db.exists("File", file_name))

	def test_someone_elses_file_is_refused(self):
		po = self.site_order()
		theirs = photo()  # uploaded by the administrator
		frappe.set_user(self.receiver)
		with self.assertRaises(frappe.PermissionError):
			self.record(po, [(40, "OK")], exit_permit_photo=theirs)
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.get_value("File", {"file_url": theirs}, "attached_to_name"))

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
		frappe.db.set_value(
			gr.RECEIPT, name, {"sp_receipt_status": gr.REJECTED, "sp_reject_reason": "الصورة غير واضحة"}
		)
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
		doc.items[0].received_qty = 1
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_my_receipts_are_mine(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		name = self.record(po, [(40, "OK")])["name"]
		self.assertIn(name, [r.name for r in gr.my_receipts()])
		frappe.set_user(self.other)
		self.assertNotIn(name, [r.name for r in gr.my_receipts()])

	def test_a_receiver_cannot_submit_their_own_receipt(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		name = self.record(po, [(40, "OK")])["name"]
		doc = frappe.get_doc(gr.RECEIPT, name)
		with self.assertRaises(frappe.PermissionError):
			doc.submit()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(gr.RECEIPT, name, "docstatus"), 0)
		admin_copy = frappe.get_doc(gr.RECEIPT, name)  # not even the admin skips the confirmation
		with self.assertRaises(frappe.ValidationError):
			admin_copy.submit()

	def test_a_store_keeper_cannot_post_a_receipt_around_the_confirmation(self):
		po = order([row(qty=5)], sp_destination_type=MAIN_STORE).insert()
		po.submit()
		receipt = make_purchase_receipt(po.name).insert()
		frappe.set_user(self.keeper)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(gr.RECEIPT, receipt.name).submit()

	def test_the_receiver_cannot_read_the_prices_on_the_receipt(self):
		po = self.site_order()
		frappe.set_user(self.receiver)
		name = self.record(po, [(40, "OK")])["name"]
		meta = frappe.get_meta(gr.RECEIPT)
		self.assertNotIn(COST_PERMLEVEL, meta.get_permlevel_access("read"))
		self.assertEqual(frappe.get_meta(gr.RECEIPT_ITEM).get_field("rate").permlevel, COST_PERMLEVEL)
		doc = frappe.get_doc(gr.RECEIPT, name)
		doc.apply_fieldlevel_read_permissions()
		self.assertFalse(doc.items[0].get("rate"))
		self.assertFalse(doc.get("grand_total"))

	def serial_order(self, qty=2):
		code = f"SP84-MTR-{frappe.generate_hash(length=6).upper()}"
		make_item(code, item_group=GROUP, has_serial_no=1, serial_no_series="SP84-.#####")
		po = order([row(qty=qty, item_code=code)], sp_destination_type=MAIN_STORE).insert()
		po.submit()
		return po

	def serial_line(self, po, serial, nameplate="upload", qty=1):
		return {
			"purchase_order_item": po.items[0].name,
			"received_qty": qty,
			"condition": "OK",
			"serial_no": serial,
			"serial_photo": photo() if nameplate == "upload" else nameplate,
		}

	def record_serials(self, po, lines):
		return gr.record_receipt(po.name, po.items[0].warehouse, lines, photo(), SIGNATURE)

	def test_a_motor_is_received_with_its_serial_and_nameplate_photo(self):
		po = self.serial_order()
		frappe.set_user(self.keeper)
		self.assertTrue(self.card(po)["lines"][0]["serial"])
		name = self.record_serials(po, [self.serial_line(po, "SP84-A1"), self.serial_line(po, "SP84-A2")])[
			"name"
		]
		frappe.set_user("Administrator")
		doc = frappe.get_doc(gr.RECEIPT, name)
		self.assertEqual([r.serial_no for r in doc.items], ["SP84-A1", "SP84-A2"])
		self.assertTrue(all(r.sp_serial_photo for r in doc.items))

	def test_a_serial_item_needs_its_serial_photo_and_one_unit_per_row(self):
		po = self.serial_order()
		frappe.set_user(self.keeper)
		for bad in (
			self.serial_line(po, ""),
			self.serial_line(po, "SP84-B1", nameplate=None),
			self.serial_line(po, "SP84-B1", qty=2),
		):
			with self.assertRaises(frappe.ValidationError):
				self.record_serials(po, [bad])

	def test_one_serial_is_received_once(self):
		po = self.serial_order()
		frappe.set_user(self.keeper)
		with self.assertRaises(frappe.ValidationError):
			self.record_serials(po, [self.serial_line(po, "SP84-C1"), self.serial_line(po, "SP84-C1")])
		self.record_serials(po, [self.serial_line(po, "SP84-C1")])
		with self.assertRaises(frappe.ValidationError):
			self.record_serials(po, [self.serial_line(po, "SP84-C1")])
