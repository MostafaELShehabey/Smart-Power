"""The supplier ledger and supplier payments (SP-86): the running balance, the station split, and
money that leaves only when the admin confirms it."""

import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.dashboards.cards import supplier_dues_week
from smart_power.sp_finance import confirmations
from smart_power.sp_finance import supplier_ledger as ledger
from smart_power.sp_finance import supplier_payment as sp
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock.purchase_orders import MAIN_STORE, enable_batches
from smart_power.tests.test_customer_payment import account
from smart_power.tests.test_goods_receipt import photo
from smart_power.tests.test_purchase_orders import COMPANY, ITEM, SUPPLIER, order, row
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

EXPENSE, CENTER = "_Test Account Cost for Goods Sold - _TC", "_Test Cost Center - _TC"
REASON = "المبلغ لا يطابق كشف البنك"


def project(name):
	found = frappe.db.get_value("Project", {"project_name": name})
	return (
		found
		or frappe.get_doc({"doctype": "Project", "project_name": name, "company": COMPANY}).insert().name
	)


def invoice(amounts, supplier, due_days=30):
	"""A submitted supplier invoice; amounts: [(project, value)]."""
	projects = {p for p, _value in amounts}
	doc = frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"supplier": supplier,
			"company": COMPANY,
			"currency": frappe.get_cached_value("Company", COMPANY, "default_currency"),
			"conversion_rate": 1,
			"posting_date": today(),
			"set_posting_time": 1,
			"due_date": add_days(today(), due_days),
			"bill_no": frappe.generate_hash(length=10),
			"project": projects.pop() if len(projects) == 1 else None,
			"items": [
				{
					"item_code": ITEM,
					"qty": 1,
					"rate": v,
					"project": p,
					"expense_account": EXPENSE,
					"cost_center": CENTER,
				}
				for p, v in amounts
			],
		}
	).insert()
	if due_days < 0:
		doc.db_set("due_date", add_days(today(), due_days))
		doc.reload()
	doc.submit()
	return doc


class TestSupplierLedger(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		enable_batches()
		cls.clerk = make_user("sp.sl.clerk@example.com", ("supplier_accounts",))
		cls.admin = make_user("sp.sl.admin@example.com", ("admin",))
		cls.other = make_user("sp.sl.other@example.com", ("site_receiver",))
		cls.bank = account("SP86 Bank Misr", "Bank", "Official", account_type="Bank")
		cls.north, cls.south = project("SP86 North"), project("SP86 South")

	def setUp(self):
		name = f"SP86 Supplier {frappe.generate_hash(length=8)}"
		group = "_Test Supplier Group"
		self.vendor = (
			frappe.get_doc({"doctype": "Supplier", "supplier_name": name, "supplier_group": group})
			.insert()
			.name
		)

	def tearDown(self):
		frappe.set_user("Administrator")

	def bill(self, amounts, due_days=30):
		return invoice(amounts, self.vendor, due_days)

	def record(self, amount, supplier=None, **kw):
		frappe.set_user(self.clerk)
		values = {
			"supplier": supplier or self.vendor,
			"company": COMPANY,
			"amount": amount,
			"account": self.bank,
			"reference_no": "TRX-86",
			"receipt_photo": photo(),
			"posting_date": today(),
			**kw,
		}
		name = sp.record_payment(values)
		frappe.set_user("Administrator")
		return name

	def pay(self, amount, **kw):
		name = self.record(amount, **kw)
		frappe.set_user(self.admin)
		sp.confirm(name)
		frappe.set_user("Administrator")
		return name

	def view(self, supplier=None, **kw):
		return ledger.supplier_ledger(supplier or self.vendor, COMPANY, **kw)

	def test_the_running_balance_and_the_station_split_agree(self):
		self.bill([(self.north, 30000)])
		self.bill([(self.north, 20000)])
		self.bill([(self.south, 50000)])
		self.pay(40000)
		data = self.view()
		self.assertEqual(data["balance"], 60000)
		self.assertEqual(data["rows"][-1]["balance"], 60000)
		self.assertEqual([r["balance"] for r in data["rows"][:3]], [30000, 50000, 100000])
		split = {r["project"]: r["amount"] for r in data["stations"]}
		self.assertEqual(flt(sum(split.values())), data["balance"])
		self.assertEqual(split[self.north], 10000)  # the earliest invoices were paid first
		self.assertEqual(split[self.south], 50000)

	def test_a_payment_linked_to_an_order_reduces_the_invoice_and_shows_on_the_order(self):
		po = order([row(qty=10, rate=6000)], sp_destination_type=MAIN_STORE).insert()
		po.submit()
		bill = make_purchase_invoice(po.name)
		bill.bill_no = frappe.generate_hash(length=10)
		bill.insert().submit()
		name = self.pay(50000, supplier=SUPPLIER, purchase_order=po.name)
		self.assertEqual(flt(frappe.db.get_value("Purchase Invoice", bill.name, "outstanding_amount")), 10000)
		self.assertEqual(flt(frappe.db.get_value("Purchase Order", po.name, "sp_paid_amount")), 50000)
		frappe.get_doc("Payment Entry", name).cancel()
		self.assertEqual(flt(frappe.db.get_value("Purchase Order", po.name, "sp_paid_amount")), 0)

	def test_a_recorded_payment_posts_nothing_until_the_admin_confirms(self):
		bill = self.bill([(self.north, 10000)])
		name = self.record(10000)
		doc = frappe.get_doc("Payment Entry", name)
		self.assertEqual((doc.docstatus, doc.sp_payment_status), (0, sp.PENDING))
		self.assertFalse(frappe.db.exists("GL Entry", {"voucher_no": name}))
		self.assertEqual(flt(frappe.db.get_value("Purchase Invoice", bill.name, "outstanding_amount")), 10000)
		task = {"reference_name": name, "task_type": sp.CONFIRM_TASK, "status": "Open"}
		self.assertTrue(frappe.db.exists("SP Task", task))
		frappe.set_user(self.admin)
		self.assertIn(name, [i["name"] for i in confirmations.pending()["items"]])
		confirmations.confirm("Payment Entry", name)
		frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual((doc.docstatus, doc.sp_payment_status), (1, sp.CONFIRMED))
		self.assertEqual(flt(frappe.db.get_value("Purchase Invoice", bill.name, "outstanding_amount")), 0)
		self.assertFalse(frappe.db.exists("SP Task", task))

	def test_a_rejected_payment_posts_nothing_and_goes_back_with_the_reason(self):
		name = self.record(10000)
		frappe.set_user(self.admin)
		sp.reject(name, REASON)
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Payment Entry", name)
		self.assertEqual(
			(doc.docstatus, doc.sp_payment_status, doc.sp_reject_reason), (0, sp.REJECTED, REASON)
		)
		self.assertFalse(frappe.db.exists("GL Entry", {"voucher_no": name}))
		task = {"reference_name": name, "assigned_to": self.clerk, "status": "Open"}
		self.assertEqual(frappe.db.get_value("SP Task", task, "description"), REASON)

	def test_only_the_admin_confirms(self):
		name = self.record(10000)
		frappe.set_user(self.clerk)
		self.assertRaises(frappe.PermissionError, sp.confirm, name)
		self.assertRaises(frappe.PermissionError, sp.reject, name, REASON)

	def test_money_cannot_go_around_the_confirmation(self):
		name = self.record(10000)
		frappe.set_user(self.clerk)
		doc = frappe.get_doc("Payment Entry", name)
		self.assertRaises(frappe.ValidationError, doc.submit)
		doc = frappe.get_doc("Payment Entry", name)
		doc.paid_amount = 1
		self.assertRaises(frappe.ValidationError, doc.save)
		frappe.set_user("Administrator")
		direct = frappe.copy_doc(frappe.get_doc("Payment Entry", name))
		direct.update({"sp_payment_status": None, "sp_recorded_by": None, "sp_receipt_photo": None})
		direct.flags.ignore_permissions = True
		direct.insert()
		frappe.set_user(self.clerk)
		direct = frappe.get_doc("Payment Entry", direct.name)
		self.assertRaises(frappe.PermissionError, direct.submit)

	def test_a_payment_needs_an_official_account_a_reference_and_its_own_receipt(self):
		self.bill([(self.north, 10000)])
		theirs = photo()  # uploaded by the administrator
		transit = account("SP86 Transit", "Cash", "Transit", self.clerk, account_type="Cash")
		for bad in ({"account": transit}, {"reference_no": " "}, {"receipt_photo": None}):
			self.assertRaises(frappe.ValidationError, self.record, 100, **bad)
		self.assertRaises(frappe.PermissionError, self.record, 100, receipt_photo=theirs)
		frappe.set_user(self.other)
		self.assertRaises(
			frappe.PermissionError,
			sp.record_payment,
			{
				"supplier": self.vendor,
				"company": COMPANY,
				"amount": 1,
				"account": self.bank,
				"reference_no": "x",
				"receipt_photo": "/x",
			},
		)

	def test_the_earliest_due_is_paid_first_and_the_rest_stays_as_an_advance(self):
		later = self.bill([(self.north, 10000)], due_days=40)
		sooner = self.bill([(self.south, 10000)], due_days=5)
		name = self.pay(15000)

		def outstanding(doc):
			return flt(frappe.db.get_value("Purchase Invoice", doc.name, "outstanding_amount"))

		self.assertEqual((outstanding(sooner), outstanding(later)), (0, 5000))
		self.pay(20000)
		self.assertEqual(outstanding(later), 0)
		self.assertEqual(self.view()["balance"], -15000)
		self.assertTrue(name)

	def test_an_invoice_for_two_stations_is_shared_by_value(self):
		self.bill([(self.north, 30000), (self.south, 10000)])
		self.pay(20000)
		data = self.view()
		split = {r["project"]: r["amount"] for r in data["stations"]}
		self.assertEqual(split, {self.north: 15000, self.south: 5000})
		self.assertEqual(flt(sum(split.values())), data["balance"])

	def test_a_period_starts_from_the_balance_carried_into_it(self):
		self.bill([(self.north, 10000)])
		data = self.view(from_date=add_days(today(), 1))
		self.assertEqual((data["opening"], data["balance"], data["rows"]), (10000, 10000, []))

	def test_a_consignment_withdrawal_is_named_on_the_ledger(self):
		po = order([row(qty=1, rate=1000)], sp_destination_type=MAIN_STORE).insert()
		po.submit()
		po.db_set("sp_is_consignment_conversion", 1)
		bill = make_purchase_invoice(po.name)
		bill.bill_no = frappe.generate_hash(length=10)
		bill.insert().submit()
		row_ = next(r for r in self.view(SUPPLIER)["rows"] if r["voucher_no"] == bill.name)
		self.assertEqual(row_["kind"], ledger.WITHDRAWAL)

	def test_dues_this_week_feed_the_finance_home(self):
		before = ledger.dues_this_week(COMPANY)
		self.bill([(self.north, 7000)], due_days=3)
		self.bill([(self.north, 9000)], due_days=30)
		after = ledger.dues_this_week(COMPANY)
		self.assertEqual(flt(after["amount"] - before["amount"]), 7000)
		self.assertEqual(supplier_dues_week(self.admin)["fieldtype"], "Currency")
		self.assertEqual(self.view()["due_this_week"], 7000)

	def test_only_supplier_accounts_open_the_ledger(self):
		frappe.set_user(self.other)
		self.assertRaises(frappe.PermissionError, ledger.supplier_ledger, self.vendor, COMPANY)
