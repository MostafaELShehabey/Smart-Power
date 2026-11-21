"""S4 Reassign, the station part (SP-79): the collection or execution owner from a date."""

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today

from smart_power.sp_stations import installments
from smart_power.sp_stations.collections import collections
from smart_power.sp_stations.reassign import apply_scheduled, reassign_station
from smart_power.tests.test_customer_payment import PHOTO, account
from smart_power.tests.test_installments import InstalmentCase
from smart_power.tests.utils import make_user

STATION, TASK, HISTORY = "SP Station", "SP Task", "SP Owner History"
REASON = "كاميليا تتابع العميل"


class TestStationReassign(InstalmentCase):
	def setUp(self):
		super().setUp()
		self.camelia = make_user("sp.ra.camelia@example.com", ("customer_followup", "followup_all"))
		self.lead = make_user("sp.ra.lead@example.com", ("lead_intake",))
		# the station opened with أميرة collecting (the shared case sets her straight in the table)
		frappe.db.set_value(
			HISTORY,
			{"parent": self.station.name, "parenttype": STATION, "role_kind": "Collection Owner"},
			"to_user",
			self.amira,
		)

	def reassign(self, kind="collection", to_user=None, from_date=None, reason=REASON, user=None):
		frappe.set_user(user or self.admin)
		try:
			return reassign_station(self.station.name, kind, to_user or self.camelia, from_date, reason)
		finally:
			frappe.set_user("Administrator")

	def cl1(self, user):
		frappe.set_user(user)
		try:
			return [r["station"] for r in collections()["stations"]]
		finally:
			frappe.set_user("Administrator")

	def due_alerts(self, user):
		return frappe.db.count(
			"Notification Log",
			{"for_user": user, "document_name": self.station.name, "subject": ("like", "Instalment due:%")},
		)

	def test_from_a_later_date_the_daily_job_moves_cl1_and_the_due_alert(self):
		installments.update_installments()  # both instalments, due within 3 days, alerted أميرة
		alerted = self.due_alerts(self.amira)
		self.assertTrue(alerted)
		result = self.reassign(from_date=add_days(today(), 3))
		self.assertFalse(result["applied"])
		self.station.reload()
		self.assertEqual(self.station.collection_owner, self.amira)  # not yet
		pending = [r for r in self.station.owner_history if r.is_pending]
		self.assertEqual([(r.to_user, r.reason) for r in pending], [(self.camelia, REASON)])
		self.assertNotIn(self.station.name, self.cl1(self.camelia))

		# the day comes: the job applies it, then the instalment alerts run
		frappe.db.set_value(HISTORY, pending[0].name, "from_date", add_to_date(now_datetime(), minutes=-1))
		self.assertEqual(apply_scheduled(), [f"{self.station.name}:collection"])
		installments.update_installments()
		self.station.reload()
		self.assertEqual(self.station.collection_owner, self.camelia)
		self.assertIn(self.station.name, self.cl1(self.camelia))
		self.assertNotIn(self.station.name, self.cl1(self.amira))
		self.assertEqual(self.due_alerts(self.camelia), alerted)  # the unpaid instalments, to her now
		self.assertEqual(self.due_alerts(self.amira), alerted)
		row = frappe.get_doc(HISTORY, pending[0].name)
		self.assertEqual((row.is_pending, row.from_user, row.to_user), (0, self.amira, self.camelia))
		self.assertEqual(apply_scheduled(), [])  # applied once

	def test_no_reason_is_refused(self):
		with self.assertRaises(frappe.MandatoryError):
			self.reassign(reason="  ")

	def test_from_today_applies_at_once_moves_the_calls_and_tells_both(self):
		call = frappe.get_doc(
			{
				"doctype": TASK,
				"subject": "Collection call",
				"task_type": "Follow-up Call",
				"assigned_to": self.amira,
				"reference_doctype": STATION,
				"reference_name": self.station.name,
			}
		).insert(ignore_permissions=True)
		other = frappe.get_doc(
			{
				"doctype": TASK,
				"subject": "Site visit",
				"task_type": "Other",
				"assigned_to": self.amira,
				"reference_doctype": STATION,
				"reference_name": self.station.name,
			}
		).insert(ignore_permissions=True)
		self.assertTrue(self.reassign()["applied"])
		self.station.reload()
		self.assertEqual(self.station.collection_owner, self.camelia)
		last = self.station.owner_history[-1]
		self.assertEqual((last.from_user, last.to_user, last.reason), (self.amira, self.camelia, REASON))
		self.assertEqual(frappe.db.get_value(TASK, call.name, "assigned_to"), self.camelia)
		self.assertEqual(frappe.db.get_value(TASK, other.name, "assigned_to"), self.amira)  # execution's
		for user in (self.amira, self.camelia):
			self.assertTrue(
				frappe.db.exists(
					"Notification Log",
					{"for_user": user, "document_name": self.station.name, "sp_event": "station_reassigned"},
				)
			)
		self.assertTrue(
			frappe.db.exists(
				"SP Review Item",
				{"category": "Reassignment", "reference_name": self.station.name, "status": "Open"},
			)
		)

	def test_who_may_reassign_and_who_may_hold_it(self):
		with self.assertRaises(frappe.PermissionError):
			self.reassign(user=self.amira)  # only the admin
		with self.assertRaises(frappe.ValidationError):
			self.reassign(to_user=self.lead)  # no collection role
		with self.assertRaises(frappe.ValidationError):
			self.reassign(kind="execution", to_user=self.camelia)  # follow-up does not execute
		with self.assertRaises(frappe.ValidationError):
			self.reassign(from_date=add_days(today(), -1))

	def test_the_owner_changes_only_through_reassign(self):
		doc = frappe.get_doc(STATION, self.station.name)
		doc.collection_owner = self.camelia
		with self.assertRaises(frappe.ValidationError):
			doc.save()  # even the admin gives a reason

	def test_a_new_reassignment_replaces_the_one_waiting(self):
		self.reassign(from_date=add_days(today(), 5))
		self.reassign(to_user=self.admin, from_date=add_days(today(), 10))
		self.station.reload()
		self.assertEqual([r.to_user for r in self.station.owner_history if r.is_pending], [self.admin])

	def test_payments_before_the_hand_over_stay_with_the_old_owner(self):
		instapay = account("SP InstaPay", "Bank", "Official", account_type="Bank")

		def payment():
			return frappe.get_doc(
				{
					"doctype": "SP Customer Payment",
					"station": self.station.name,
					"amount": 1000,
					"method": "Payment Method-INSTAPAY",
					"receiving_account": instapay,
					"reference_no": "SP79",
					"receipt_photo": PHOTO,
				}
			).insert()

		before = payment()
		self.reassign()
		after = payment()
		self.assertEqual((before.collection_owner, after.collection_owner), (self.amira, self.camelia))
		before.save()
		self.assertEqual(
			frappe.db.get_value("SP Customer Payment", before.name, "collection_owner"), self.amira
		)
