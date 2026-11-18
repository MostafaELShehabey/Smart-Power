"""Transfer orders (SP-88): stock leaves the store for Transit, and reaches the site only as far as
the site confirms it."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_stock import transfers as t
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import bookings as b
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_purchase_orders import COMPANY, ITEM, station
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

GROUP = "_Test Item Group"


def stock(item, warehouse, qty=100):
	entry = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"purpose": "Material Receipt",
			"company": COMPANY,
			"items": [{"item_code": item, "qty": qty, "t_warehouse": warehouse, "basic_rate": 100}],
		}
	).insert()
	entry.submit()


def on_hand(item, warehouse):
	return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": warehouse}, "actual_qty"))


class TestTransfers(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_centers(COMPANY)
		cls.main = wh.warehouse_of(COMPANY, wh.MAIN)
		cls.showroom = wh.warehouse_of(COMPANY, wh.SHOWROOM)
		cls.transit = wh.warehouse_of(COMPANY, wh.TRANSIT)
		if not cls.transit:
			root = frappe.db.get_value(
				"Warehouse", {"company": COMPANY, "is_group": 1, "parent_warehouse": ("is", "not set")}
			)
			cls.transit = (
				frappe.get_doc(
					{
						"doctype": "Warehouse",
						"warehouse_name": "SP88 Transit",
						"company": COMPANY,
						"parent_warehouse": root,
						"warehouse_type": wh.TRANSIT,
					}
				)
				.insert()
				.name
			)
		cls.buyer = make_user("sp.tr.amira@example.com", ("purchase_officer",))
		cls.keeper = make_user("sp.tr.gaber@example.com", ("main_store_keeper",))
		cls.showroom_keeper = make_user("sp.tr.hussein@example.com", ("showroom_store_keeper",))
		cls.receiver = make_user("sp.tr.mostafa@example.com", ("site_receiver",))
		cls.other = make_user("sp.tr.other@example.com", ("site_receiver",))
		stock(ITEM, cls.main, 1000)
		stock(ITEM, cls.showroom, 100)

	def setUp(self):
		self.station = station()
		frappe.db.set_value("SP Station", self.station.name, "site_receiver", self.receiver)
		self.site = wh.site_warehouse(self.station.project)

	def tearDown(self):
		frappe.set_user("Administrator")

	def create(self, qty=10, kind=wh.MAIN, transport=t.OTHER, item=ITEM):
		frappe.set_user(self.buyer)
		name = t.create_transfer(
			{
				"station": self.station.name,
				"source_kind": kind,
				"transport": transport,
				"planned_date": today(),
				"items": [{"item_code": item, "qty": qty}],
			}
		)
		frappe.set_user("Administrator")
		return name

	def issue(self, name, user=None, serials=None):
		frappe.set_user(user or self.keeper)
		entry = t.issue_transfer(name, serials)
		frappe.set_user("Administrator")
		return entry

	def confirm(self, name, qty):
		rows = t._issued_rows(frappe.db.get_value(t.ORDER, name, "sp_issue_entry"))
		frappe.set_user(self.receiver)
		result = t.confirm_transfer(name, [{"row": rows[0].name, "qty": qty}])
		frappe.set_user("Administrator")
		return result

	def test_issuing_moves_ten_rolls_from_the_store_to_transit(self):
		main, transit = on_hand(ITEM, self.main), on_hand(ITEM, self.transit)
		name = self.create()
		self.assertEqual(frappe.db.get_value(t.ORDER, name, "sp_transfer_status"), t.CREATED)
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{
					"reference_name": name,
					"task_type": t.TASK_ISSUE,
					"assigned_to": self.keeper,
					"status": "Open",
				},
			)
		)
		self.assertEqual(on_hand(ITEM, self.main), main)
		entry = self.issue(name)
		self.assertEqual((on_hand(ITEM, self.main), on_hand(ITEM, self.transit)), (main - 10, transit + 10))
		doc = frappe.get_doc(t.ENTRY, entry)
		self.assertEqual((doc.add_to_transit, doc.project, doc.docstatus), (1, self.station.project, 1))
		self.assertEqual(doc.owner, self.keeper)
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{
					"reference_name": name,
					"task_type": t.TASK_RECEIVE,
					"assigned_to": self.receiver,
					"status": "Open",
				},
			)
		)

	def test_the_transfer_note_prints_without_a_price(self):
		entry = self.issue(self.create())
		note = t.transfer_print(frappe.get_doc(t.ENTRY, entry))
		self.assertEqual((note.station, note.site, note.source), (self.station.name, self.site, self.main))
		self.assertEqual((note.lines[0]["item_code"], note.lines[0]["qty"]), (ITEM, 10))
		self.assertNotIn("rate", note.lines[0])
		html = frappe.get_print(t.ENTRY, entry, print_format="SP Transfer Note")
		self.assertIn(entry, html)

	def test_confirming_nine_leaves_one_in_transit_and_tells_purchasing(self):
		name = self.create()
		self.issue(name)
		transit = on_hand(ITEM, self.transit)
		result = self.confirm(name, 9)
		self.assertEqual((result["status"], result["short"]), (t.DISCREPANCY, 1))
		self.assertEqual((on_hand(ITEM, self.site), on_hand(ITEM, self.transit)), (9, transit - 9))
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{
					"reference_name": name,
					"task_type": t.TASK_DIFFERENCE,
					"assigned_to": self.buyer,
					"status": "Open",
				},
			)
		)
		entry = frappe.get_doc(t.ENTRY, result["entry"])
		self.assertEqual(entry.owner, self.receiver)
		self.assertEqual(
			(entry.project, entry.outgoing_stock_entry),
			(self.station.project, frappe.db.get_value(t.ORDER, name, "sp_issue_entry")),
		)

	def test_the_last_unit_arriving_closes_the_difference(self):
		name = self.create()
		self.issue(name)
		self.confirm(name, 9)
		frappe.set_user(self.receiver)
		left = t.transfers_to_confirm()
		self.assertEqual([c["lines"][0]["left"] for c in left if c["name"] == name], [1])
		result = self.confirm(name, 1)
		self.assertEqual(result["status"], t.RECEIVED)
		self.assertEqual(on_hand(ITEM, self.site), 10)
		self.assertFalse(
			frappe.db.exists(
				"SP Task", {"reference_name": name, "task_type": t.TASK_DIFFERENCE, "status": "Open"}
			)
		)

	def test_more_than_was_issued_is_refused(self):
		name = self.create()
		self.issue(name)
		self.assertRaises(frappe.ValidationError, self.confirm, name, 11)

	def test_showroom_stock_moves_at_cost(self):
		name = self.create(qty=2, kind=wh.SHOWROOM)
		entry = frappe.get_doc(t.ENTRY, self.issue(name, self.showroom_keeper))
		self.assertEqual(entry.items[0].s_warehouse, self.showroom)
		self.assertEqual(flt(entry.items[0].basic_rate), 100)

	def test_only_the_stores_keeper_issues_and_only_the_sites_receiver_confirms(self):
		name = self.create()
		frappe.set_user(self.showroom_keeper)
		self.assertRaises(frappe.PermissionError, t.issue_transfer, name)
		self.issue(name)
		frappe.set_user(self.other)
		self.assertRaises(frappe.PermissionError, t.confirm_transfer, name, [])

	def test_only_purchasing_creates(self):
		frappe.set_user(self.keeper)
		self.assertRaises(frappe.PermissionError, t.create_transfer, {})

	def test_a_transfer_is_issued_once(self):
		name = self.create()
		self.issue(name)
		self.assertRaises(frappe.ValidationError, self.issue, name)

	def test_jumbo_transport_opens_an_expected_booking_and_cancelling_drops_it(self):
		name = self.create(transport=t.JUMBO)
		booking = frappe.db.get_value(
			b.BOOKING, {"transfer_order": name}, ["status", "source", "station", "planned_date"], as_dict=True
		)
		self.assertEqual(
			(booking.status, booking.source, booking.station), (b.EXPECTED, b.TRANSFER, self.station.name)
		)
		frappe.set_user(self.buyer)
		t.cancel_transfer(name)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(t.ORDER, name, "sp_transfer_status"), t.CANCELLED)
		self.assertEqual(frappe.db.get_value(b.BOOKING, {"transfer_order": name}, "status"), b.CANCELLED)

	def test_a_serial_item_leaves_with_its_serials(self):
		code = make_item("SP88-MOTOR", item_group=GROUP, has_serial_no=1, is_stock_item=1).name
		serials = ["SP88-S1", "SP88-S2"]
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"company": COMPANY,
				"items": [
					{
						"item_code": code,
						"qty": 2,
						"t_warehouse": self.main,
						"basic_rate": 100,
						"use_serial_batch_fields": 1,
						"serial_no": "\n".join(serials),
					}
				],
			}
		).insert()
		entry.submit()
		name = self.create(qty=2, item=code)
		row = frappe.db.get_value("Material Request Item", {"parent": name})
		self.assertRaises(frappe.ValidationError, self.issue, name, None, {row: "SP88-S1"})
		self.issue(name, None, {row: "\n".join(serials)})
		self.assertRaises(frappe.ValidationError, self.confirm, name, 1)
		self.assertEqual(self.confirm(name, 2)["status"], t.RECEIVED)
		self.assertEqual(frappe.db.get_value("Serial No", "SP88-S1", "warehouse"), self.site)
