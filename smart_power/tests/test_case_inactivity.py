"""The case-inactivity rule (SP-71): an open case with no action for X days alerts its owner and
the admin once, again every X days while untouched, and not after a call."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime

from smart_power.sp_sales.followup import INACTIVE_EVENT, check_inactivity, log_call
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule, set_setting

load_erpnext_test_data()

LIMIT, IDLE = 5, 6  # sp-allow-number: the story's X = 5, a case last touched 6 days ago
INTERESTED = "Call Result-INTERESTED"


class TestCaseInactivity(IntegrationTestCase):
	def setUp(self):
		set_setting(case_inactivity_days=LIMIT)
		set_rule("case_inactive", "Warn")
		self.admin = make_user("sp.inact.admin@example.com", ("admin",))
		self.case = make_case()
		self.owner = self.case.follow_up_owner
		self.idle_since(IDLE)

	def idle_since(self, days, alerted_days_ago=None):
		values = {"last_action_at": add_days(now_datetime(), -days)}
		if alerted_days_ago is not None:
			values["last_inactive_alert"] = add_days(now_datetime(), -alerted_days_ago)
		frappe.db.set_value("SP Case", self.case.name, values, update_modified=False)

	def alerts(self, user):
		return frappe.db.count(
			"Notification Log",
			{"for_user": user, "document_name": self.case.name, "sp_event": INACTIVE_EVENT},
		)

	def test_six_idle_days_alert_the_owner_and_the_admin_once(self):
		self.assertIn(self.case.name, check_inactivity())
		self.assertEqual((self.alerts(self.owner), self.alerts(self.admin)), (1, 1))
		self.assertNotIn(self.case.name, check_inactivity())  # once, not every run
		self.assertEqual(self.alerts(self.owner), 1)
		hit = frappe.db.exists("SP Rule Hit", {"rule_key": "case_inactive", "reference_name": self.case.name})
		self.assertTrue(hit)

	def test_a_call_the_next_day_stops_the_alerts(self):
		check_inactivity()
		log_call(self.case.name, INTERESTED, "اتصال متابعة")
		self.assertNotIn(self.case.name, check_inactivity())
		self.assertEqual(self.alerts(self.owner), 1)

	def test_the_alert_repeats_every_x_days_while_untouched(self):
		self.idle_since(IDLE + LIMIT + 1, alerted_days_ago=LIMIT + 1)
		self.assertIn(self.case.name, check_inactivity())
		self.idle_since(IDLE + LIMIT + 1, alerted_days_ago=1)
		self.assertNotIn(self.case.name, check_inactivity())

	def test_closed_cases_and_an_empty_setting_are_left_alone(self):
		set_setting(case_inactivity_days=0)
		self.assertEqual(check_inactivity(), [])
		set_setting(case_inactivity_days=LIMIT)
		frappe.db.set_value("SP Case", self.case.name, {"status": "Lost"}, update_modified=False)
		self.assertNotIn(self.case.name, check_inactivity())
