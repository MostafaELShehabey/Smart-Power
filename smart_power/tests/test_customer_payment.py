"""Record a customer payment, confirm or reject it (SP-114)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate, today

from smart_power.sp_finance.customer_payment import confirm, receiving_accounts, reject
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import ensure_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
PHOTO = "/files/receipt.jpg"


def account(name, parent_type, kind, holder=None, account_type=None):
	full = f"{name} - _TC"
	if not frappe.db.exists("Account", full):
		parent = frappe.db.get_value(
			"Account", {"company": COMPANY, "is_group": 1, "account_type": parent_type}
		) or frappe.db.get_value(
			"Account", {"company": COMPANY, "is_group": 1, "account_name": "Current Assets"}
		)
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": name,
				"company": COMPANY,
				"parent_account": parent,
				"account_type": account_type,
				"sp_receiving_kind": kind,
				"sp_holder": holder,
			}
		).insert()
	return full


class TestCustomerPayment(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		set_setting(large_payment_threshold=100000)
		self.amira = make_user("sp.cp.amira@example.com", ("project_manager", "collection_officer"))
		self.camelia = make_user("sp.cp.camelia@example.com", ("customer_followup", "followup_all"))
		self.admin = make_user("sp.cp.admin@example.com", ("admin",))
		self.instapay = account("SP InstaPay", "Bank", "Official", account_type="Bank")
		self.camelia_cash = account("SP Camelia Cash", "Cash", "Transit", self.camelia, account_type="Cash")
		q = make_quotation(rate=200000, valid_days=3, save=False)
		q.insert()
		q.set(
			"payment_schedule",
			[
				{"due_date": today(), "invoice_portion": 50, "payment_amount": 100000},
				{"due_date": add_days(today(), 30), "invoice_portion": 50, "payment_amount": 100000},
			],
		)
		q.save()
		q.submit()
		approve_version(q.name)
		result = ensure_contract(q.sp_case)
		so = frappe.get_doc("Sales Order", result["sales_order"])
		so.submit()
		self.station = result["station"]

	def tearDown(self):
		frappe.set_user("Administrator")

	def record(self, user, amount, method, account, photo=PHOTO, **kw):
		frappe.set_user(user)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SP Customer Payment",
					"station": self.station,
					"amount": amount,
					"method": method,
					"receiving_account": account,
					"reference_no": "REF",
					"receipt_photo": photo,
					**kw,
				}
			).insert()
			doc.submit()
			return doc
		finally:
			frappe.set_user("Administrator")

	def station_money(self):
		return frappe.db.get_value(
			"SP Station",
			self.station,
			["paid_amount", "pending_amount", "next_due_date", "next_due_amount"],
			as_dict=True,
		)

	def test_recorded_is_pending_with_a_task_and_paid_unchanged(self):
		doc = self.record(self.amira, 25000, "Payment Method-INSTAPAY", self.instapay)
		self.assertEqual(doc.status, "Pending")
		money = self.station_money()
		self.assertEqual((flt(money.paid_amount), flt(money.pending_amount)), (0, 25000))
		task = frappe.get_all(
			"SP Task",
			{"reference_name": doc.name, "task_type": "Receipt to Confirm", "status": "Open"},
			["assigned_to", "description"],
		)
		self.assertEqual(task[0].assigned_to, self.admin)
		self.assertEqual(task[0].description, PHOTO)

	def test_confirm_posts_to_the_account_and_pays_the_oldest_instalment(self):
		doc = self.record(self.amira, 25000, "Payment Method-INSTAPAY", self.instapay)
		frappe.set_user(self.admin)
		pe = frappe.get_doc("Payment Entry", confirm(doc.name))
		frappe.set_user("Administrator")
		self.assertEqual((pe.paid_to, flt(pe.paid_amount), pe.docstatus), (self.instapay, 25000, 1))
		self.assertEqual(pe.references[0].reference_doctype, "Sales Order")
		money = self.station_money()
		self.assertEqual((flt(money.paid_amount), flt(money.pending_amount)), (25000, 0))
		# the first instalment (today) still owes 75,000; the second is untouched
		self.assertEqual(
			(getdate(money.next_due_date), flt(money.next_due_amount)), (getdate(today()), 75000)
		)
		self.assertEqual(frappe.db.get_value("SP Customer Payment", doc.name, "status"), "Confirmed")
		self.assertFalse(frappe.db.exists("SP Task", {"reference_name": doc.name, "status": "Open"}))

	def test_cash_into_own_transit_needs_no_photo_and_raises_its_balance(self):
		from erpnext.accounts.utils import get_balance_on

		before = flt(get_balance_on(self.camelia_cash))
		doc = self.record(self.camelia, 8000, "Payment Method-CASH", self.camelia_cash, photo=None)
		frappe.set_user(self.admin)
		confirm(doc.name)
		frappe.set_user("Administrator")
		self.assertEqual(flt(get_balance_on(self.camelia_cash)) - before, 8000)

	def test_only_official_or_own_transit_and_a_photo(self):
		self.assertIn(self.camelia_cash, receiving_accounts(COMPANY, self.camelia))
		self.assertNotIn(self.camelia_cash, receiving_accounts(COMPANY, self.amira))
		with self.assertRaises(frappe.ValidationError):
			self.record(self.amira, 1000, "Payment Method-CASH", self.camelia_cash, photo=None)  # not hers
		with self.assertRaises(frappe.ValidationError):
			self.record(self.amira, 1000, "Payment Method-INSTAPAY", self.instapay, photo=None)

	def test_reject_posts_nothing_and_tells_the_recorder(self):
		doc = self.record(self.amira, 25000, "Payment Method-INSTAPAY", self.instapay)
		with self.assertRaises(frappe.PermissionError):
			frappe.set_user(self.amira)
			confirm(doc.name)
		frappe.set_user(self.admin)
		reject(doc.name, "الإيصال غير واضح")
		frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual((doc.status, doc.docstatus, doc.reject_reason), ("Rejected", 2, "الإيصال غير واضح"))
		self.assertFalse(doc.payment_entry)
		self.assertEqual(flt(self.station_money().pending_amount), 0)
		self.assertTrue(
			frappe.db.exists("Notification Log", {"document_name": doc.name, "for_user": self.amira})
		)

	def test_paid_to_a_third_party_posts_supplier_against_the_customer(self):
		doc = self.record(
			self.amira,
			12000,
			"Payment Method-THIRD_PARTY",
			None,
			third_party_type="Supplier",
			third_party="_Test Supplier",
		)
		frappe.set_user(self.admin)
		je = frappe.get_doc("Journal Entry", confirm(doc.name))
		frappe.set_user("Administrator")
		parties = {(a.party_type, a.party): (flt(a.debit), flt(a.credit)) for a in je.accounts}
		self.assertEqual(parties[("Supplier", "_Test Supplier")], (12000, 0))
		customer = frappe.db.get_value("SP Station", self.station, "customer")
		self.assertEqual(parties[("Customer", customer)], (0, 12000))

	def test_a_large_payment_is_flagged(self):
		doc = self.record(self.amira, 150000, "Payment Method-INSTAPAY", self.instapay)
		subjects = frappe.get_all("SP Task", {"reference_name": doc.name}, pluck="subject")
		self.assertTrue(subjects[0].startswith("⚠"))

	def test_a_confirmed_deposit_runs_the_deposit_automation(self):
		q = make_quotation(rate=90000, valid_days=3)
		q.submit()
		approve_version(q.name)
		frappe.set_user(self.camelia)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SP Customer Payment",
					"case": q.sp_case,
					"is_deposit": 1,
					"amount": 20000,
					"method": "Payment Method-CASH",
					"receiving_account": self.camelia_cash,
				}
			).insert()
			doc.submit()
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("SP Station", {"case": q.sp_case}))  # pending: nothing yet
		frappe.set_user(self.admin)
		confirm(doc.name)
		frappe.set_user("Administrator")
		station = frappe.db.get_value(
			"SP Station", {"case": q.sp_case}, ["name", "paid_amount"], as_dict=True
		)
		self.assertEqual(flt(station.paid_amount), 20000)
		self.assertEqual(frappe.db.get_value("SP Case", q.sp_case, "status"), "Won")
