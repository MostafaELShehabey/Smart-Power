"""Cancel a station after the deposit (SP-176): refunds, reservations, orders, the site's goods."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_finance import supplier_payment
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.cancel import cancel_preview, cancel_station
from smart_power.sp_stations.setup import enable_stock_reservation
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_customer_payment import account
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user

load_erpnext_test_data()

COMPANY, ITEM, SUPPLIER = "_Test Company", "_Test Item", "_Test Supplier"
STATION, ENTRY = "SP Station", "Payment Entry"
REASON = "العميل ألغى التعاقد"
DEPOSIT = 300000


class TestStationCancel(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Currency Exchange", {"from_currency": "EGP", "to_currency": "INR"}):
			frappe.get_doc(
				{
					"doctype": "Currency Exchange",
					"date": "2020-01-01",
					"from_currency": "EGP",
					"to_currency": "INR",
					"exchange_rate": 1.7,
					"for_buying": 1,
					"for_selling": 1,
				}
			).insert()
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
		cls.instapay = account("SP InstaPay", "Bank", "Official", account_type="Bank")
		cls.admin = make_user("sp.sc.admin@example.com", ("admin",))
		cls.cash_holder = make_user("sp.sc.holder@example.com", ("customer_followup",))
		cls.transit = account("SP Holder Cash", "Cash", "Transit", cls.cash_holder, account_type="Cash")

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		self.receipt(self.main, 1)  # one in the main store; the quote asks for three
		quote = make_quotation(rate=100000, valid_days=3, save=False)
		quote.items[0].qty = 3
		quote.insert()
		quote.submit()
		approve_version(quote.name)
		self.case, self.customer = quote.sp_case, quote.party_name
		self.deposit = self.receive(DEPOSIT, self.instapay, is_deposit=1)
		self.so = frappe.db.get_value("Sales Order", {"sp_case": self.case, "docstatus": 1})
		self.station = frappe.get_doc(STATION, frappe.db.get_value("Sales Order", self.so, "sp_station"))

	def receipt(self, warehouse, qty, rate=100):
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": COMPANY,
				"items": [{"item_code": ITEM, "qty": qty, "t_warehouse": warehouse, "basic_rate": rate}],
			}
		).insert()
		se.submit()
		return se

	def receive(self, amount, paid_to, is_deposit=0):
		values = {"sp_is_deposit": 1, "sp_case": self.case} if is_deposit else {}
		if not is_deposit:
			values["project"] = self.station.project
		pe = frappe.get_doc(
			{
				"doctype": ENTRY,
				"payment_type": "Receive",
				"company": COMPANY,
				"party_type": "Customer",
				"party": self.customer,
				"paid_from": "_Test Receivable - _TC",
				"paid_to": paid_to,
				"paid_amount": amount,
				"received_amount": amount,
				"reference_no": "SP176",
				"reference_date": today(),
				**values,
			}
		).insert()
		pe.submit()
		return pe

	def cancel(self, user=None, reason=REASON, **kw):
		frappe.set_user(user or self.admin)
		try:
			return cancel_station(self.station.name, reason, **kw)
		finally:
			frappe.set_user("Administrator")

	def test_a_300000_instapay_deposit_is_refunded_from_instapay_pending_and_reservations_go(self):
		self.assertTrue(
			frappe.db.count("Stock Reservation Entry", {"voucher_no": self.so, "docstatus": 1})
		)  # the deposit reserved the one in stock
		result = self.cancel()
		[name] = result["refunds"]
		refund = frappe.get_doc(ENTRY, name)
		self.assertEqual(
			(refund.payment_type, refund.party, refund.paid_from, flt(refund.paid_amount)),
			("Pay", self.customer, self.instapay, DEPOSIT),
		)
		self.assertEqual((refund.docstatus, refund.sp_payment_status), (0, "Pending"))
		self.assertEqual(refund.sp_refund_of, self.deposit.name)
		self.assertEqual(
			frappe.db.count("Stock Reservation Entry", {"voucher_no": self.so, "docstatus": 1}), 0
		)
		self.station.reload()
		self.assertEqual(
			(self.station.status, str(self.station.cancelled_on), flt(self.station.refund_amount)),
			("Cancelled", today(), DEPOSIT),
		)
		self.assertEqual(self.station.cancel_reason, REASON)
		self.assertEqual(frappe.db.get_value("SP Case", self.case, "status"), "Lost")
		self.assertEqual(frappe.db.get_value("Sales Order", self.so, "status"), "Closed")
		self.assertTrue(
			frappe.db.exists(
				"SP Review Item", {"category": "Station Cancellation", "reference_name": self.station.name}
			)
		)
		# the admin confirms it in the confirmations centre (A1)
		items = [i for i in supplier_payment.pending_items({}) if i["name"] == name]
		self.assertEqual((items[0]["kind"], items[0]["station"]), ("Customer refund", self.station.name))
		frappe.set_user(self.admin)
		supplier_payment.confirm(name)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(ENTRY, name, "docstatus"), 1)

	def test_an_inverter_on_site_goes_back_to_the_main_store_at_cost(self):
		site = self.station.site_warehouse
		self.receipt(site, 1, rate=250)  # delivered to the site
		before = flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": self.main}, "actual_qty"))
		result = self.cancel()
		[line] = result["lines"]
		self.assertEqual((line["item_code"], flt(line["qty"]), line["fate"]), (ITEM, 1, "To stock"))
		entry = frappe.get_doc("Stock Entry", line["stock_entry"])
		self.assertEqual(
			(entry.docstatus, entry.items[0].s_warehouse, entry.items[0].t_warehouse), (1, site, self.main)
		)
		self.assertEqual(
			flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": site}, "actual_qty")), 0
		)
		after = flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": self.main}, "actual_qty"))
		self.assertEqual(after - before, 1)
		incoming = frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_no": entry.name, "warehouse": self.main, "is_cancelled": 0},
			"incoming_rate",
		)
		self.assertEqual(flt(incoming), 250)  # at cost
		self.station.reload()
		self.assertEqual(self.station.cancel_lines[0].stock_entry, entry.name)

	def test_every_confirmed_payment_is_refunded_and_transit_cash_from_an_official_account(self):
		later = self.receive(20000, self.transit)
		preview = cancel_preview(self.station.name)
		self.assertEqual([r["payment"] for r in preview["refunds"]], [self.deposit.name, later.name])
		self.assertEqual([r["official"] for r in preview["refunds"]], [True, False])
		with self.assertRaises(frappe.MandatoryError):
			self.cancel()  # the transit payment needs an official account
		result = self.cancel(accounts={later.name: self.instapay})
		refunds = {
			frappe.db.get_value(ENTRY, n, "sp_refund_of"): frappe.db.get_value(
				ENTRY, n, ["paid_from", "paid_amount"]
			)
			for n in result["refunds"]
		}
		self.assertEqual(refunds[later.name], (self.instapay, 20000))
		self.assertEqual(flt(result["refund_amount"]), DEPOSIT + 20000)

	def test_draft_orders_go_and_submitted_ones_are_flagged(self):
		# earlier tests' cancellations put stock back, so the deposit may have drafted none: make one
		po = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"supplier": SUPPLIER,
				"company": COMPANY,
				"schedule_date": today(),
				"project": self.station.project,
				"sp_station": self.station.name,
				"items": [
					{
						"item_code": ITEM,
						"qty": 2,
						"rate": 100,
						"warehouse": self.main,
						"schedule_date": today(),
					}
				],
			}
		)
		po.insert()
		drafts = frappe.get_all(
			"Purchase Order", {"sp_station": self.station.name, "docstatus": 0}, pluck="name"
		)
		self.assertIn(po.name, drafts)
		result = self.cancel()
		self.assertEqual(sorted(result["deleted_orders"]), sorted(drafts))
		self.assertFalse(frappe.db.exists("Purchase Order", {"name": ("in", drafts)}))

	def test_a_line_received_for_the_station_goes_back_to_its_supplier(self):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		site = self.station.site_warehouse
		po = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"supplier": SUPPLIER,
				"company": COMPANY,
				"schedule_date": today(),
				"project": self.station.project,
				"sp_station": self.station.name,
				"items": [
					{"item_code": ITEM, "qty": 1, "rate": 100, "warehouse": site, "schedule_date": today()}
				],
			}
		).insert()
		po.submit()
		pr = make_purchase_receipt(po.name)
		pr.flags.sp_confirming = True
		pr.insert()
		pr.submit()
		preview = cancel_preview(self.station.name)
		self.assertEqual(
			[(l["item_code"], l["purchase_receipt"]) for l in preview["lines"]], [(ITEM, pr.name)]
		)
		result = self.cancel(fates={ITEM: "Return to supplier"})
		ret = frappe.get_doc("Purchase Receipt", result["lines"][0]["purchase_return"])
		self.assertEqual((ret.is_return, ret.return_against, ret.docstatus), (1, pr.name, 1))
		self.assertEqual((flt(ret.items[0].qty), ret.items[0].warehouse), (-1, site))
		self.assertEqual(
			flt(frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": site}, "actual_qty")), 0
		)
		self.assertEqual(result["flagged_orders"], [po.name])
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{"reference_doctype": "Purchase Order", "reference_name": po.name, "status": "Open"},
			)
		)

	def test_only_the_admin_with_a_reason_and_only_through_cancel(self):
		manager = make_user("sp.sc.pm@example.com", ("project_manager",))
		with self.assertRaises(frappe.PermissionError):
			self.cancel(user=manager)
		with self.assertRaises(frappe.MandatoryError):
			self.cancel(reason=" ")
		doc = frappe.get_doc(STATION, self.station.name)
		doc.status = "Cancelled"
		with self.assertRaises(frappe.ValidationError):
			doc.save()  # no refunds that way
		self.cancel()
		with self.assertRaises(frappe.ValidationError):
			self.cancel()  # once
