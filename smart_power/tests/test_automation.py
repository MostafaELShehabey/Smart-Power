"""X9 Automations (SP-135): an overdue instalment gives its collection owner a task and the admin
an alert, exactly once; a paused automation does nothing; record events, conditions and the dry
run; a broken automation never blocks a save."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.sp_core import automation as am
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import (
	load_erpnext_test_data,
	make_customer,
	make_quotation,
	make_user,
	sign_contract,
)

load_erpnext_test_data()

COMPANY, ROW = "_Test Company", "Payment Schedule"


def automation(title, **kw):
	return frappe.get_doc({"doctype": am.AUTOMATION, "title": title, **kw}).insert()


class TestAutomation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		from smart_power.notify import sync_events

		sync_events()
		cls.collector = make_user("sp.au.collector@example.com", ("collection_officer",))
		cls.admin = make_user("sp.au.admin@example.com", ("admin",))
		cls.sales = make_user("sp.au.sales@example.com", ("customer_followup",))
		quote = make_quotation(rate=20000, valid_days=3)
		quote.submit()
		approve_version(quote.name)
		result = make_contract(quote.sp_case)
		sign_contract(result["sales_order"])
		cls.station = result["station"]
		frappe.db.set_value("SP Station", cls.station, "collection_owner", cls.collector)
		cls.row = frappe.get_all(
			ROW, {"parent": result["sales_order"], "parenttype": "Sales Order"}, pluck="name"
		)[0]

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		# the class shares one transaction: each test starts with no automation and no task
		for table in (am.LOG, "SP Automation Action", "SP Automation Condition", am.AUTOMATION):
			frappe.db.delete(table)
		frappe.db.delete("SP Task", {"assigned_to": self.collector})
		am.clear_cache()
		self.addCleanup(am.clear_cache)

	def overdue(self, days_ago):
		frappe.db.set_value(ROW, self.row, {"due_date": add_days(today(), -days_ago), "sp_status": "Overdue"})

	def overdue_rule(self, **kw):
		return automation(
			"Instalment overdue 3 days",
			doctype_name=ROW,
			trigger=am.DAYS_AFTER,
			date_field="due_date",
			offset_days=3,
			conditions=[{"field": "sp_status", "op": "=", "value": "Overdue"}],
			actions=[
				{
					"kind": am.TASK,
					"recipient_type": am.FIELD,
					"recipient": "parent.sp_station.collection_owner",
					"task_type": "Other",
					"message": "Call the customer: instalment {{ doc.name }} is 3 days late",
				},
				{"kind": am.NOTIFY, "recipient_type": am.USER, "recipient": self.admin},
			],
			**kw,
		)

	def tasks(self):
		return frappe.get_all(
			"SP Task", {"assigned_to": self.collector, "status": "Open", "task_type": "Other"}, pluck="name"
		)

	def alerts(self):
		return frappe.db.count("Notification Log", {"for_user": self.admin, "sp_event": am.EVENT})

	def test_an_instalment_three_days_overdue_fires_once(self):
		rule = self.overdue_rule()
		self.overdue(3)
		before = self.alerts()
		self.assertEqual(am.run_daily(), 1)
		self.assertEqual(am.run_daily(), 0)  # exactly once
		task = frappe.get_doc("SP Task", self.tasks()[0])
		self.assertEqual(task.reference_doctype, "Sales Order")  # a row is opened through its contract
		self.assertIn("3 days late", task.subject)
		self.assertEqual(len(self.tasks()), 1)
		self.assertEqual(self.alerts() - before, 1)
		self.assertEqual(frappe.db.count(am.LOG, {"automation": rule.name}), 1)

	def test_a_paused_automation_does_nothing(self):
		self.overdue_rule(is_active=0)
		self.overdue(3)
		self.assertEqual(am.run_daily(), 0)
		self.assertFalse(self.tasks())

	def test_a_backlog_older_than_the_automation_is_left_alone(self):
		self.overdue_rule()
		self.overdue(30)  # its day came 27 days before the automation existed
		self.assertEqual(am.run_daily(), 0)
		self.assertEqual(am.run_daily(on=add_days(today(), 1)), 0)

	def test_not_overdue_yet_waits_and_fires_when_it_is(self):
		self.overdue_rule()
		self.overdue(3)
		frappe.db.set_value(ROW, self.row, "sp_status", "Due")
		self.assertEqual(am.run_daily(), 0)
		frappe.db.set_value(ROW, self.row, "sp_status", "Overdue")
		self.assertEqual(am.run_daily(on=add_days(today(), 1)), 1)  # still caught the next day

	def test_the_dry_run_shows_without_doing(self):
		rule = self.overdue_rule()
		self.overdue(3)
		result = am.test(rule.name, self.row)
		self.assertTrue(result["matches"])
		self.assertEqual([a["users"] for a in result["actions"]], [[self.collector], [self.admin]])
		self.assertFalse(self.tasks())
		self.assertFalse(frappe.db.exists(am.LOG, {"automation": rule.name}))
		frappe.set_user(self.sales)
		self.assertRaises(frappe.PermissionError, am.test, rule.name, self.row)

	def test_record_events_and_conditions(self):
		automation(
			"New featured customer",
			doctype_name="Customer",
			trigger=am.ON_CREATE,
			conditions=[{"field": "customer_name", "op": "contains", "value": "شركة"}],
			actions=[{"kind": am.NOTIFY, "recipient_type": am.ROLE, "recipient": "SP Admin"}],
		)
		automation(
			"Customer group changed",
			doctype_name="Customer",
			trigger=am.ON_CHANGE,
			watch_field="customer_group",
			actions=[{"kind": am.ASSIGN, "recipient_type": am.USER, "recipient": self.sales}],
		)
		before = self.alerts()
		person = make_customer("01009991351", "عميل أتمتة فرد")
		self.assertEqual(self.alerts(), before)  # the condition does not hold
		make_customer("01009991352", "شركة أتمتة")
		self.assertEqual(self.alerts() - before, 1)
		doc = frappe.get_doc("Customer", person)
		doc.save()
		self.assertFalse(frappe.db.exists("ToDo", {"reference_name": person, "allocated_to": self.sales}))
		doc.customer_group = frappe.get_all(
			"Customer Group", {"is_group": 0, "name": ("!=", doc.customer_group)}, pluck="name"
		)[0]
		doc.save()
		self.assertTrue(frappe.db.exists("ToDo", {"reference_name": person, "allocated_to": self.sales}))

	def test_a_broken_automation_never_blocks_a_save(self):
		rule = automation(
			"Broken task",
			doctype_name="Customer",
			trigger=am.ON_CREATE,
			actions=[
				{"kind": am.TASK, "recipient_type": am.USER, "recipient": self.sales, "task_type": "Other"}
			],
		)
		frappe.db.set_value("SP Automation Action", {"parent": rule.name}, "task_type", "No Such Type")
		frappe.clear_document_cache(am.AUTOMATION, rule.name)
		# frappe.log_error commits, which would end this test's transaction: count the calls instead
		with patch.object(frappe, "log_error") as logged:
			customer = make_customer("01009991353", "عميل أتمتة معطلة")
		self.assertTrue(frappe.db.exists("Customer", customer))  # the save went through
		self.assertEqual(logged.call_count, 1)
		self.assertFalse(frappe.db.exists(am.LOG, {"automation": rule.name}))

	def test_the_message_fills_in_the_record(self):
		self.overdue_rule()
		self.overdue(3)
		frappe.db.set_value(
			"SP Automation Action",
			{"parent": "Instalment overdue 3 days", "kind": am.TASK},
			"message",
			"{{ doc.sp_status }} at {{ doc.parent.sp_station }}; {{ doc.parent.__class__ }}",
		)
		frappe.clear_document_cache(am.AUTOMATION, "Instalment overdue 3 days")
		subject = am.test("Instalment overdue 3 days", self.row)["actions"][0]["subject"]
		# a field it does not know is read as a field, never as a Python attribute: it comes out empty
		self.assertEqual(subject, f"Overdue at {self.station}; ")

	def test_a_wrong_date_field_is_refused(self):
		self.assertRaises(
			frappe.ValidationError,
			automation,
			"Bad date",
			doctype_name=ROW,
			trigger=am.DAYS_AFTER,
			date_field="payment_amount",
			actions=[{"kind": am.NOTIFY, "recipient_type": am.ROLE, "recipient": "SP Admin"}],
		)
