"""The 24 h quote clock (SP-48)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from smart_power.sp_sales.quote_clock import AMBER, ON_TIME, OVERDUE, SENT, amber_seconds_left, clock
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import set_setting


def hours_ago(hours):
	return add_to_date(now_datetime(), hours=-hours)


class TestQuoteClock(IntegrationTestCase):
	def setUp(self):
		set_setting(quote_due_hours=24, quote_amber_hours=18)

	def test_states(self):
		for hours, state in ((2, ON_TIME), (18.5, AMBER), (30, OVERDUE)):
			self.assertEqual(clock({"creation": hours_ago(hours)})["state"], state, hours)
		self.assertEqual(
			clock({"creation": hours_ago(30), "quote_sent_at": hours_ago(10)}),
			{"hours": 20.0, "state": SENT, "seconds_left": None},
		)

	def test_countdown(self):
		# a new request counts down from 24:00; amber in the last 6 h; negative once overdue
		self.assertAlmostEqual(clock({"creation": now_datetime()})["seconds_left"], 24 * 3600, delta=60)
		self.assertAlmostEqual(clock({"creation": hours_ago(24.5)})["seconds_left"], -1800, delta=60)
		self.assertEqual(amber_seconds_left(), 6 * 3600)

	def test_settings_decide(self):
		set_setting(quote_due_hours=48, quote_amber_hours=40)
		self.assertEqual(clock({"creation": hours_ago(30)})["state"], ON_TIME)

	def test_case_gets_its_due_time_and_stops_when_sent(self):
		case = make_case()
		self.assertEqual(
			get_datetime(case.quote_due_at).replace(microsecond=0),
			add_to_date(get_datetime(case.creation), hours=24).replace(microsecond=0),
		)
		self.assertFalse(case.quote_sent_at)
		for status in ("Draft", "Sent to customer"):
			case.status = status
			case.save()
		self.assertTrue(case.quote_sent_at)
		self.assertEqual(clock(case)["state"], SENT)

	def test_amber_setting_is_seeded(self):
		self.assertTrue(frappe.get_meta("Smart Power Settings").get_field("quote_amber_hours"))
