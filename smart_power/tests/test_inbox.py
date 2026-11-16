"""The task inbox (SP-39, G3): the task service, snooze, and the inbox with inline actions."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, flt, getdate, now_datetime, today

from smart_power.sp_core import inbox
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import ensure_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_customer_payment import PHOTO, account
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"


class TestTaskService(IntegrationTestCase):
	def setUp(self):
		self.aya = make_user("sp.inbox.aya@example.com", ("quote_creator",))

	def test_one_open_task_per_user_and_record_and_closing_them(self):
		ref = ("User", self.aya)  # any record will do for the service
		first = inbox.create_task("Other", *ref, [self.aya, self.aya], "افحص هذا", amount=1500)
		again = inbox.create_task("Other", *ref, self.aya, "افحص هذا")
		self.assertEqual((len(first), again), (1, []))  # the open task is not given twice
		self.assertEqual(frappe.db.get_value("SP Task", first[0], "amount"), 1500)
		self.assertEqual(inbox.close_tasks(*ref, task_type="Other"), first)
		self.assertEqual(frappe.db.get_value("SP Task", first[0], "status"), "Done")

	def test_a_snoozed_task_comes_back_when_its_time_has_passed(self):
		(name,) = inbox.create_task("Other", "User", "Guest", self.aya, "لاحقًا")
		frappe.db.set_value("SP Task", name, "snoozed_until", add_to_date(now_datetime(), hours=-1))
		inbox.unsnooze()
		self.assertIsNone(frappe.db.get_value("SP Task", name, "snoozed_until"))


class TestInboxActions(IntegrationTestCase):
	"""The story's checks: أميرة's payment gives the admin a task; Confirm inline posts it; snooze."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		set_setting(large_payment_threshold=100000)
		self.amira = make_user("sp.inbox.amira@example.com", ("project_manager", "collection_officer"))
		self.admin = make_user("sp.inbox.admin@example.com", ("admin",))
		self.other = make_user("sp.inbox.other@example.com", ("collection_officer",))
		self.instapay = account("SP InstaPay", "Bank", "Official", account_type="Bank")
		q = make_quotation(rate=200000, valid_days=3)
		q.submit()
		approve_version(q.name)
		result = ensure_contract(q.sp_case)
		frappe.get_doc("Sales Order", result["sales_order"]).submit()
		self.station = result["station"]

	def tearDown(self):
		frappe.set_user("Administrator")

	def payment(self, amount=25000):
		frappe.set_user(self.amira)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SP Customer Payment",
					"station": self.station,
					"amount": amount,
					"method": "Payment Method-INSTAPAY",
					"receiving_account": self.instapay,
					"reference_no": "REF",
					"receipt_photo": PHOTO,
				}
			).insert()
			doc.submit()
			return doc
		finally:
			frappe.set_user("Administrator")

	def admin_tasks(self, **kw):
		frappe.set_user(self.admin)
		try:
			return inbox.my_tasks(**kw)
		finally:
			frappe.set_user("Administrator")

	def task_of(self, doc, **kw):
		return next(t for t in self.admin_tasks(**kw)["tasks"] if t.reference_name == doc.name)

	def test_the_admin_confirms_a_payment_from_the_inbox(self):
		doc = self.payment()
		task = self.task_of(doc)
		self.assertEqual(
			(task.task_type, flt(task.amount), task.image, task.inline),
			("Payment to Confirm", 25000, PHOTO, True),
		)
		frappe.set_user(self.admin)
		inbox.act(task.name, "approve")
		frappe.set_user("Administrator")
		payment = frappe.db.get_value(
			"SP Customer Payment", doc.name, ["status", "payment_entry"], as_dict=True
		)
		self.assertEqual(payment.status, "Confirmed")
		self.assertEqual(
			frappe.db.get_value("Payment Entry", payment.payment_entry, "docstatus"), 1
		)  # posted
		self.assertEqual(frappe.db.get_value("SP Task", task.name, "status"), "Done")

	def test_reject_needs_a_reason_and_only_the_assignee_acts(self):
		task = self.task_of(self.payment())
		frappe.set_user(self.other)
		with self.assertRaises(frappe.PermissionError):
			inbox.act(task.name, "approve")
		frappe.set_user(self.admin)
		with self.assertRaises(frappe.ValidationError):
			inbox.act(task.name, "reject", "")
		inbox.act(task.name, "reject", "الإيصال غير واضح")
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("SP Customer Payment", task.reference_name, "status"), "Rejected"
		)

	def test_a_snoozed_task_reappears_when_its_time_passes(self):
		task = self.task_of(self.payment())
		tomorrow_nine = add_to_date(getdate(today()), days=1, hours=9)  # sp-allow-number: 9:00
		frappe.set_user(self.admin)
		inbox.snooze(task.name, str(tomorrow_nine))
		frappe.set_user("Administrator")
		self.assertNotIn(task.name, [t.name for t in self.admin_tasks()["tasks"]])
		self.assertIn(task.name, [t.name for t in self.admin_tasks(snoozed=1)["tasks"]])
		# the time passes (moved back instead of waiting); the hourly job brings it back
		frappe.db.set_value("SP Task", task.name, "snoozed_until", add_to_date(now_datetime(), minutes=-1))
		inbox.unsnooze()
		self.assertIn(task.name, [t.name for t in self.admin_tasks()["tasks"]])
