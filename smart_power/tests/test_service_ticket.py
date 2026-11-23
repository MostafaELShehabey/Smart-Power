"""SV1 Service ticket (SP-72): follow-up opens a ticket on a customer's station with its warranty
status; installations get a task, move it step by step, and the opener is told."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, today

from smart_power.sp_site import service as sv
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock import warranty
from smart_power.tests.test_field_entry import list_value
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"


class TestServiceTicket(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		cls.camelia = make_user("sp.svc.camelia@example.com", ("lead_intake", "customer_followup"))
		cls.mostafa = make_user("sp.svc.mostafa@example.com", ("installation_manager", "warranty_service"))
		cls.issue = list_value("Service Issue", "INVERTER_FAULT")
		cls.station = (
			frappe.get_doc({"doctype": "SP Station", "customer": "_Test Customer", "company": COMPANY})
			.insert()
			.name
		)
		cls.other = (
			frappe.get_doc({"doctype": "SP Station", "customer": "_Test Customer 1", "company": COMPANY})
			.insert()
			.name
		)
		for serial, item, months, started in (
			("SP72-INV-1", "_Test Item", 36, add_months(today(), -30)),  # the inverter: still covered
			("SP72-PMP-1", "_Test Item 2", 24, add_months(today(), -30)),  # the pump: out
		):
			warranty.upsert(
				serial,
				item,
				{"station": cls.station, "source": "Station", "start_date": started, "months": months},
			)

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def ticket(self, **values):
		frappe.set_user(self.camelia)
		try:
			return frappe.get_doc(
				{
					"doctype": sv.TICKET,
					"customer": "_Test Customer",
					"station": self.station,
					"issue_type": self.issue,
					"description": "الإنفرتر لا يعمل",
					**values,
				}
			).insert()
		finally:
			frappe.set_user("Administrator")

	def test_the_ticket_shows_each_components_warranty(self):
		cover = sv.warranty_for(self.station)
		by_serial = {c["serial_no"]: c["covered"] for c in cover["components"]}
		self.assertEqual(by_serial, {"SP72-INV-1": True, "SP72-PMP-1": False})
		doc = self.ticket()
		self.assertEqual((doc.status, doc.opened_by, doc.warranty_status), (sv.OPEN, self.camelia, sv.PARTLY))
		self.assertIn("SP72-INV-1", doc.warranty_details)
		self.assertEqual(sv.warranty_for(self.other)["status"], sv.NONE)

	def test_an_urgent_ticket_gives_installations_a_task_and_a_notification(self):
		doc = self.ticket(urgency="Urgent")
		task = frappe.db.get_value(
			"SP Task",
			{"reference_name": doc.name, "task_type": "Service Ticket", "assigned_to": self.mostafa},
			["status", "priority"],
			as_dict=True,
		)
		self.assertEqual((task.status, task.priority), ("Open", "High"))
		self.assertTrue(
			frappe.db.exists("Notification Log", {"document_name": doc.name, "for_user": self.mostafa})
		)

	def test_installations_move_it_and_the_opener_is_told_when_it_closes(self):
		doc = self.ticket()
		frappe.set_user(self.camelia)
		self.assertRaises(frappe.PermissionError, sv.move, doc.name, sv.ACCEPTED)
		frappe.set_user(self.mostafa)
		self.assertRaises(frappe.ValidationError, sv.move, doc.name, sv.CLOSED)  # one step at a time
		for status in (sv.ACCEPTED, sv.IN_PROGRESS, sv.CLOSED):
			sv.move(doc.name, status)
		frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual((doc.status, doc.assigned_to), (sv.CLOSED, self.mostafa))
		self.assertTrue(doc.closed_at)
		self.assertFalse(frappe.db.exists("SP Task", {"reference_name": doc.name, "status": "Open"}))
		told = frappe.get_all("Notification Log", {"document_name": doc.name, "for_user": self.camelia})
		self.assertEqual(len(told), 3)  # accepted, in progress, closed
		doc.description = "x"
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_the_station_must_be_the_customers_and_a_status_cannot_be_typed_in(self):
		self.assertRaises(frappe.ValidationError, self.ticket, station=self.other)
		doc = self.ticket()
		doc.status = sv.CLOSED
		doc.save()
		self.assertEqual(frappe.db.get_value(sv.TICKET, doc.name, "status"), sv.OPEN)
