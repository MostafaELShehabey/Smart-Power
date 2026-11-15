"""A1 Confirmations centre (SP-115): the queue, bulk confirm, reject, preview."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_finance.confirmations import bulk_confirm, bulk_result, pending, preview, reject
from smart_power.tests.test_customer_payment import account
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"
PHOTO = "/files/receipt.jpg"


class TestConfirmations(IntegrationTestCase):
	def setUp(self):
		from smart_power.sp_sales.quotation import approve_version
		from smart_power.sp_stations.contract import ensure_contract
		from smart_power.sp_stock import warehouses as wh

		wh.seed_warehouses(COMPANY)
		self.amira = make_user("sp.cf.amira@example.com", ("project_manager", "collection_officer"))
		self.admin = make_user("sp.cf.admin@example.com", ("admin",))
		self.instapay = account("SP CF InstaPay", "Bank", "Official", account_type="Bank")
		self.post = account("SP CF Post", "Bank", "Official", account_type="Bank")
		q = make_quotation(rate=500000, valid_days=3)
		q.submit()
		approve_version(q.name)
		self.station = ensure_contract(q.sp_case)["station"]
		# clear what earlier tests left pending
		for name in frappe.get_all("SP Customer Payment", {"status": "Pending"}, pluck="name"):
			frappe.db.set_value("SP Customer Payment", name, "status", "Rejected")

	def tearDown(self):
		frappe.set_user("Administrator")

	def record(self, amount, account, method):
		frappe.set_user(self.amira)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SP Customer Payment",
					"station": self.station,
					"amount": amount,
					"work_date": today(),
					"method": method,
					"receiving_account": account,
					"receipt_photo": PHOTO,
				}
			).insert()
			doc.submit()
			return doc.name
		finally:
			frappe.set_user("Administrator")

	def test_filter_instapay_and_bulk_confirm_four_of_six(self):
		instapay = [self.record(1000 * (i + 1), self.instapay, "Payment Method-INSTAPAY") for i in range(4)]
		post = [self.record(500, self.post, "Payment Method-POST") for _ in range(2)]
		frappe.set_user(self.admin)
		queue = pending({"account": self.instapay})
		self.assertEqual(sorted(i["name"] for i in queue["items"]), sorted(instapay))
		self.assertEqual(queue["amount"], 10000)
		key = bulk_confirm([{"doctype": "SP Customer Payment", "name": n} for n in instapay])
		result = bulk_result(key)
		self.assertTrue(result["done"])
		self.assertTrue(all(r["ok"] for r in result["results"]))
		left = pending()
		self.assertEqual(sorted(i["name"] for i in left["items"]), sorted(post))
		for name in instapay:
			pe = frappe.db.get_value("SP Customer Payment", name, "payment_entry")
			self.assertEqual(frappe.db.get_value("Payment Entry", pe, "docstatus"), 1)

	def test_a_failure_does_not_stop_the_others(self):
		good = self.record(1000, self.instapay, "Payment Method-INSTAPAY")
		bad = self.record(2000, self.instapay, "Payment Method-INSTAPAY")
		frappe.db.set_value("SP Customer Payment", bad, "status", "Confirmed")  # no longer pending
		frappe.set_user(self.admin)
		result = bulk_result(
			bulk_confirm(
				[
					{"doctype": "SP Customer Payment", "name": bad},
					{"doctype": "SP Customer Payment", "name": good},
				]
			)
		)
		self.assertEqual([r["ok"] for r in result["results"]], [False, True])
		self.assertEqual(frappe.db.get_value("SP Customer Payment", good, "status"), "Confirmed")

	def test_reject_tells_the_recorder_with_a_task(self):
		name = self.record(3000, self.instapay, "Payment Method-INSTAPAY")
		frappe.set_user(self.admin)
		reject("SP Customer Payment", name, "المبلغ غير ظاهر في الكشف")
		frappe.set_user("Administrator")
		task = frappe.get_all(
			"SP Task", {"reference_name": name, "assigned_to": self.amira}, ["description", "status"]
		)
		self.assertEqual((task[0].description, task[0].status), ("المبلغ غير ظاهر في الكشف", "Open"))
		self.assertTrue(frappe.db.exists("Notification Log", {"document_name": name, "for_user": self.amira}))

	def test_preview_shows_the_lines_center_and_station(self):
		name = self.record(4000, self.instapay, "Payment Method-INSTAPAY")
		frappe.set_user(self.admin)
		lines = preview("SP Customer Payment", name)
		before = frappe.db.count("Payment Entry")
		self.assertEqual(frappe.db.count("Payment Entry"), before)  # nothing posted
		project = frappe.db.get_value("SP Station", self.station, "project")
		debit = next(line for line in lines if line["debit"])
		credit = next(line for line in lines if line["credit"])
		self.assertEqual((debit["account"], flt(debit["debit"])), (self.instapay, 4000))
		self.assertEqual(flt(credit["credit"]), 4000)
		self.assertTrue(credit["party"])
		self.assertTrue(debit["cost_center"])
		self.assertEqual({line["project"] for line in lines}, {project})

	def test_only_the_admin(self):
		frappe.set_user(self.amira)
		with self.assertRaises(frappe.PermissionError):
			pending()
