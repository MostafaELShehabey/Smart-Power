"""Purchase orders (SP-82): the destination sets the warehouse, batches keep their own date and
price, the status follows the receipts, and only the cost roles read the supplier's prices."""

import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from smart_power.dashboards.cards import deliveries_due_week
from smart_power.permissions import COST_PERMLEVEL
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import ensure_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock.purchase_orders import (
	MAIN_STORE,
	SHOWROOM_STORE,
	SITE_DELIVERY,
	enable_batches,
)
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user

load_erpnext_test_data()

COMPANY, ITEM, SUPPLIER = "_Test Company", "_Test Item", "_Test Supplier"
SOON, LATER = 10, 25


def station():
	quote = make_quotation(rate=50000, valid_days=3, save=False)
	quote.insert()
	quote.set(
		"payment_schedule",
		[{"due_date": add_days(today(), 30), "invoice_portion": 100, "payment_amount": 50000}],
	)
	quote.save()
	quote.submit()
	approve_version(quote.name)
	return frappe.get_doc("SP Station", ensure_contract(quote.sp_case)["station"])


def row(batch=1, days=SOON, rate=5100, qty=10, **kw):
	return {
		"item_code": ITEM,
		"qty": qty,
		"rate": rate,
		"sp_batch_no": batch,
		"schedule_date": add_days(today(), days),
		**kw,
	}


def order(rows=None, **kw):
	return frappe.get_doc(
		{
			"doctype": "Purchase Order",
			"supplier": SUPPLIER,
			"company": COMPANY,
			"currency": frappe.get_cached_value("Company", COMPANY, "default_currency"),
			"conversion_rate": 1,
			"transaction_date": today(),
			"schedule_date": add_days(today(), SOON),
			"items": rows or [row()],
			**kw,
		}
	)


class TestPurchaseOrders(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		enable_batches()

	def test_a_delivery_to_site_goes_to_the_stations_warehouse(self):
		st = station()
		po = order(sp_station=st.name, sp_destination_type=SITE_DELIVERY).insert()
		expected = wh.site_warehouse(st.project)
		self.assertEqual((po.set_warehouse, po.items[0].warehouse), (expected, expected))
		self.assertEqual((po.project, po.items[0].project), (st.project, st.project))
		self.assertEqual(po.sp_source, "Manual")

	def test_the_stores_have_their_own_warehouses(self):
		main = order(sp_destination_type=MAIN_STORE).insert()
		self.assertEqual(main.items[0].warehouse, wh.warehouse_of(COMPANY, wh.MAIN))
		showroom = order(sp_destination_type=SHOWROOM_STORE).insert()
		self.assertEqual(showroom.set_warehouse, wh.warehouse_of(COMPANY, wh.SHOWROOM))

	def test_a_delivery_to_site_needs_a_station(self):
		with self.assertRaises(frappe.ValidationError):
			order(sp_destination_type=SITE_DELIVERY).insert()

	def test_a_shared_order_delivers_each_row_to_its_station(self):
		first, second = station(), station()
		po = order(
			[row(sp_station=first.name), row(batch=2, days=LATER, sp_station=second.name)],
			sp_destination_type=SITE_DELIVERY,
		).insert()
		self.assertEqual(
			[r.warehouse for r in po.items],
			[wh.site_warehouse(first.project), wh.site_warehouse(second.project)],
		)
		self.assertFalse(po.set_warehouse)

	def test_two_batches_keep_their_own_date_and_price(self):
		po = order([row(1, SOON, 5100), row(2, LATER, 5250)], sp_destination_type=MAIN_STORE).insert()
		self.assertEqual([(r.sp_batch_no, r.rate) for r in po.items], [(1, 5100), (2, 5250)])
		self.assertEqual(getdate(po.schedule_date), getdate(add_days(today(), SOON)))
		self.assertEqual(getdate(po.sp_next_delivery), getdate(add_days(today(), SOON)))

	def test_a_batch_has_one_date(self):
		with self.assertRaises(frappe.ValidationError):
			order([row(1, SOON), row(1, LATER)], sp_destination_type=MAIN_STORE).insert()

	def status(self, po):
		return frappe.db.get_value("Purchase Order", po.name, "sp_status")

	def receive(self, po, qty):
		receipt = make_purchase_receipt(po.name)
		receipt.items = receipt.items[:1]
		receipt.items[0].qty = qty
		receipt.insert()
		receipt.submit()
		return receipt

	def test_the_status_follows_the_receipts(self):
		po = order([row(1, SOON), row(2, LATER)], sp_destination_type=MAIN_STORE).insert()
		self.assertEqual(self.status(po), "Draft")
		po.submit()
		self.assertEqual(self.status(po), "Sent")
		self.receive(po, 10)
		self.assertEqual(self.status(po), "Partly received")
		self.assertEqual(
			getdate(frappe.db.get_value("Purchase Order", po.name, "sp_next_delivery")),
			getdate(add_days(today(), LATER)),
		)
		last = self.receive(frappe.get_doc("Purchase Order", po.name), 10)
		self.assertEqual(self.status(po), "Received")
		self.assertIsNone(frappe.db.get_value("Purchase Order", po.name, "sp_next_delivery"))
		last.cancel()  # a cancelled receipt puts the order back
		self.assertEqual(self.status(po), "Partly received")

	def test_a_closed_and_a_cancelled_order(self):
		closed = order(sp_destination_type=MAIN_STORE).insert()
		closed.submit()
		frappe.get_doc("Purchase Order", closed.name).update_status("Closed")
		self.assertEqual(self.status(closed), "Closed")
		cancelled = order(sp_destination_type=MAIN_STORE).insert()
		cancelled.submit()
		frappe.get_doc("Purchase Order", cancelled.name).cancel()
		self.assertEqual(self.status(cancelled), "Cancelled")

	def test_the_store_keeper_cannot_read_the_prices(self):
		meta = frappe.get_meta("Purchase Order Item")
		self.assertEqual(meta.get_field("rate").permlevel, COST_PERMLEVEL)
		keeper = make_user("sp.po.keeper@example.com", ("main_store_keeper",))
		officer = make_user("sp.po.officer@example.com", ("purchase_officer",))
		parent = frappe.get_meta("Purchase Order")
		frappe.set_user(keeper)
		try:
			self.assertNotIn(COST_PERMLEVEL, parent.get_permlevel_access("read"))
		finally:
			frappe.set_user(officer)
		try:
			self.assertIn(COST_PERMLEVEL, parent.get_permlevel_access("read"))
		finally:
			frappe.set_user("Administrator")

	def test_the_home_card_counts_this_weeks_deliveries(self):
		before = deliveries_due_week("Administrator")["value"]
		po = order([row(days=3)], sp_destination_type=MAIN_STORE).insert()
		po.submit()
		self.assertEqual(deliveries_due_week("Administrator")["value"], before + 1)
