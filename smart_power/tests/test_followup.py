"""Following a case up (SP-67): call log, next call task, revision alert, lost, sale-price view."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, get_datetime, now_datetime

from smart_power.sp_core.documents import seed_quote_template
from smart_power.sp_quotes.quote_send import send_quote
from smart_power.sp_sales.followup import case_view, log_call, mark_lost
from smart_power.tests.test_quote_send import blank_pdf
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

INTERESTED, WANTS_REVISION, PRICE_OBJECTION = (
	"Call Result-INTERESTED",
	"Call Result-WANTS_REVISION",
	"Call Result-PRICE_OBJECTION",
)


def call_tasks(case, status="Open"):
	return frappe.get_all(
		"SP Task",
		{"reference_name": case, "task_type": "Follow-up Call", "status": status},
		["name", "due_at", "assigned_to"],
	)


class TestFollowUp(IntegrationTestCase):
	def setUp(self):
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		seed_quote_template()
		set_setting(followup_delay_days=1)
		self.quote = make_quotation()
		self.case = self.quote.sp_case
		with patch("frappe.get_print", return_value=blank_pdf()):
			send_quote(self.quote.name, channel="In person")

	def test_interested_with_a_next_call_schedules_it_and_follows_up(self):
		first = call_tasks(self.case)
		self.assertEqual(len(first), 1)  # from sending the quote
		thursday = add_days(now_datetime(), 3).replace(hour=11, minute=0, second=0, microsecond=0)
		log_call(self.case, INTERESTED, "مهتم بالعرض", str(thursday))
		self.assertEqual(frappe.db.get_value("SP Task", first[0].name, "status"), "Done")
		open_tasks = call_tasks(self.case)
		self.assertEqual(len(open_tasks), 1)
		self.assertEqual(get_datetime(open_tasks[0].due_at), thursday)
		self.assertEqual(frappe.db.get_value("SP Case", self.case, "status"), "Follow-up")

	def test_wants_revision_tells_the_quote_creator(self):
		creator = make_user("sp.fu.creator@example.com", ("quote_creator",))
		frappe.db.set_value("SP Case", self.case, "quote_creator", creator)
		log_call(self.case, WANTS_REVISION, "يريد إنفرتر أكبر")
		subjects = frappe.get_all(
			"Notification Log", {"document_name": self.case, "for_user": creator}, pluck="subject"
		)
		self.assertTrue(any("يريد إنفرتر أكبر" in s for s in subjects), subjects)

	def test_a_call_without_a_next_date_leaves_no_open_call_task(self):
		log_call(self.case, PRICE_OBJECTION, "السعر عالي")
		self.assertEqual(call_tasks(self.case), [])

	def test_lost_closes_the_case_with_its_reason(self):
		log_call(self.case, "Call Result-LOST", "اشترى من غيرنا")
		mark_lost(self.case, "Lost Reason-PRICE_CHECK_ONLY", "استفسار فقط")
		case = frappe.get_doc("SP Case", self.case)
		self.assertEqual((case.status, case.lost_reason), ("Lost", "Lost Reason-PRICE_CHECK_ONLY"))
		with self.assertRaises(frappe.ValidationError):
			log_call(self.case, INTERESTED)  # a closed case takes no more calls

	def test_view_shows_calls_and_the_quote_at_sale_prices_only(self):
		log_call(self.case, INTERESTED, "مكالمة أولى")
		view = case_view(self.case)
		self.assertEqual(view["calls"][0]["result_label"], "مهتم")
		self.assertEqual(view["quote"]["name"], self.quote.name)
		data = json.dumps(view, default=str)
		for word in ("cost", "profit", "margin"):
			self.assertNotIn(word, data)

	def test_checks(self):
		with self.assertRaises(frappe.ValidationError):
			log_call(self.case, "Lost Reason-PRICE_CHECK_ONLY")  # not a call result
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "SP Call Log",
					"case": self.case,
					"result": INTERESTED,
					"call_time": now_datetime(),
					"next_call_at": add_days(now_datetime(), -1),
				}
			).insert()
