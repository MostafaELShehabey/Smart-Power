"""Hourly quote-clock alerts and the quote_24h rule (SP-48)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from smart_power.sp_sales.quote_alerts import check_quote_clock, recipients
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import make_user, set_rule, set_setting


def aged(case, hours):
	"""Pretend the request was made `hours` ago."""
	frappe.db.set_value(
		"SP Case", case.name, "creation", add_to_date(now_datetime(), hours=-hours), update_modified=False
	)


def alerts_for(case):
	return frappe.get_all(
		"Notification Log", {"document_type": "SP Case", "document_name": case.name}, pluck="for_user"
	)


class TestQuoteAlerts(IntegrationTestCase):
	def setUp(self):
		set_setting(quote_due_hours=24, quote_amber_hours=18)
		set_rule("quote_24h", "Warn")
		self.aya = make_user("sp.alert.aya@example.com", ("quote_creator",))
		self.maha = make_user("sp.alert.maha@example.com", ("quote_creator", "marketing_agent"))
		self.admin = make_user("sp.alert.admin@example.com", ("admin",))

	def test_amber_once(self):
		case = make_case(quote_creator=self.aya)
		aged(case, 19)
		check_quote_clock()
		self.assertEqual(frappe.db.get_value("SP Case", case.name, "quote_alert"), "Amber")
		self.assertTrue({self.aya, self.admin} <= set(alerts_for(case)))
		self.assertNotIn(self.maha, alerts_for(case))  # the case has its quote creator
		count = len(alerts_for(case))
		check_quote_clock()
		self.assertEqual(len(alerts_for(case)), count)

	def test_overdue_fires_the_rule(self):
		case = make_case(quote_creator=self.aya)
		aged(case, 30)
		check_quote_clock()
		self.assertEqual(frappe.db.get_value("SP Case", case.name, "quote_alert"), "Overdue")
		self.assertTrue(
			frappe.db.exists("SP Rule Hit", {"rule_key": "quote_24h", "reference_name": case.name})
		)
		self.assertTrue(frappe.db.exists("SP Review Item", {"reference_name": case.name, "status": "Open"}))
		self.assertIn(self.aya, alerts_for(case))

	def test_overdue_says_request_over_24_hours_once(self):
		case = make_case(quote_creator=self.aya)
		aged(case, 24.2)
		# an Arabic reader, while the job runs in the site's English (BUG-22)
		frappe.db.set_value("User", self.aya, "language", "ar")
		lang = frappe.local.lang
		frappe.local.lang = "en"
		try:
			check_quote_clock()
			check_quote_clock()
		finally:
			frappe.local.lang = lang
		subjects = frappe.get_all(
			"Notification Log", {"document_name": case.name, "for_user": self.aya}, pluck="subject"
		)
		self.assertEqual(len(subjects), 1)
		self.assertTrue(subjects[0].startswith("طلب تجاوز 24 ساعة"), subjects[0])

	def test_unclaimed_request_alerts_every_quote_creator(self):
		case = make_case()
		self.assertTrue({self.aya, self.maha, self.admin} <= set(recipients(case)))

	def test_sent_or_on_time_cases_are_left_alone(self):
		on_time = make_case()
		aged(on_time, 2)
		sent = make_case()
		for status in ("Draft", "Sent to customer"):
			sent.status = status
			sent.save()
		aged(sent, 30)
		check_quote_clock()
		self.assertFalse(alerts_for(on_time) or alerts_for(sent))

	def test_rule_off_sends_nothing(self):
		set_rule("quote_24h", "Off")
		case = make_case(quote_creator=self.aya)
		aged(case, 30)
		check_quote_clock()
		self.assertFalse(alerts_for(case))
		self.assertFalse(
			frappe.db.exists("SP Rule Hit", {"rule_key": "quote_24h", "reference_name": case.name})
		)

	def test_rule_can_only_warn(self):
		self.assertTrue(frappe.db.get_value("SP Rule Setting", "quote_24h", "never_block"))
		self.assertIn(
			"smart_power.sp_sales.quote_alerts.check_quote_clock",
			frappe.get_hooks("scheduler_events")["cron"]["*/15 * * * *"],
		)
