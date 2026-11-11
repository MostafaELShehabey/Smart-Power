"""SP Case: the sales spine (SP-46)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services.lists import by_code
from smart_power.sp_sales.case import touch
from smart_power.tests.utils import make_customer, make_user


def make_case(**kw):
	values = {
		"doctype": "SP Case",
		"customer": make_customer("01002003001", "عميل حالة"),
		"channel": "Call",
		"follow_up_owner": make_user("sp.case.owner@example.com", ("lead_intake", "customer_followup")),
		**kw,
	}
	return frappe.get_doc(values).insert()


class TestCase(IntegrationTestCase):
	def test_opens_as_quote_request_with_owners_in_history(self):
		creator = make_user("sp.case.creator@example.com", ("quote_creator",))
		case = make_case(quote_creator=creator)
		self.assertTrue(case.name.startswith("CS-"), case.name)
		self.assertEqual(case.status, "Quote request")
		self.assertEqual(case.mobile, "01002003001")
		self.assertEqual(
			{(r.role_kind, r.to_user) for r in case.owner_history},
			{
				("Requested By", "Administrator"),
				("Quote Creator", creator),
				("Follow-up Owner", "sp.case.owner@example.com"),
			},
		)
		self.assertTrue(case.last_action_at)

	def test_follow_up_owner_is_required(self):
		with self.assertRaises(frappe.MandatoryError):
			make_case(follow_up_owner=None)

	def test_lost_needs_a_reason(self):
		case = make_case()
		case.status = "Lost"
		with self.assertRaises(frappe.MandatoryError):
			case.save()
		case.reload()  # a failed save leaves the in-memory copy stale
		case.status = "Lost"
		case.lost_reason = by_code("Lost Reason", "PRICE_CHECK_ONLY")
		case.save()
		self.assertEqual(case.status, "Lost")

	def test_values_from_the_wrong_list_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_case(system_types=[{"system_type": by_code("Call Result", "NO_ANSWER")}])
		case = make_case(system_types=[{"system_type": by_code("System Type", "PUMP")}])
		case.status = "Lost"
		case.lost_reason = by_code("System Type", "PUMP")
		with self.assertRaises(frappe.ValidationError):
			case.save()

	def test_won_sets_the_date(self):
		case = make_case()
		for status in ("Draft", "Sent to customer", "Follow-up", "Won"):  # the workflow's path
			case.status = status
			case.save()
		self.assertTrue(case.won_on)

	def test_touch_marks_the_last_action(self):
		case = make_case()
		frappe.db.set_value(
			"SP Case", case.name, "last_action_at", "2026-01-01 00:00:00", update_modified=False
		)
		touch(case.name)
		self.assertGreater(str(frappe.db.get_value("SP Case", case.name, "last_action_at")), "2026-11")
