"""Q3 quote request queue (SP-48)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, get_fullname, now_datetime

from smart_power.sp_sales.quote_queue import get_queue, take
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

# loaded once, outside any test: it commits (start_quote's test needs a quotation)
load_erpnext_test_data()


def as_user(user, fn, *args):
	frappe.set_user(user)
	try:
		return fn(*args)
	finally:
		frappe.set_user("Administrator")


class TestQuoteQueue(IntegrationTestCase):
	def setUp(self):
		set_setting(quote_due_hours=24, quote_amber_hours=18)
		self.aya = make_user("sp.queue.aya@example.com", ("quote_creator",))
		self.maha = make_user("sp.queue.maha@example.com", ("quote_creator", "marketing_agent"))
		self.old = make_case(system_types=[{"system_type": "System Type-PUMP"}])
		frappe.db.set_value(
			"SP Case",
			self.old.name,
			"creation",
			add_to_date(now_datetime(), hours=-20),
			update_modified=False,
		)
		self.new = make_case()

	def test_unclaimed_oldest_first_with_the_clock(self):
		rows = as_user(self.aya, get_queue, "Unclaimed")
		names = [r.name for r in rows]
		self.assertLess(names.index(self.old.name), names.index(self.new.name))
		old = next(r for r in rows if r.name == self.old.name)
		self.assertEqual(old["state"], "Amber")
		self.assertEqual(old["system_type"], "طلمبات (غاطس)")

	def test_take_moves_it_to_mine(self):
		as_user(self.aya, take, self.old.name)
		self.assertIn(self.old.name, [r.name for r in as_user(self.aya, get_queue, "Mine")])
		self.assertNotIn(self.old.name, [r.name for r in as_user(self.maha, get_queue, "Unclaimed")])

	def test_a_taken_request_shows_who_took_it(self):
		as_user(self.aya, take, self.old.name)
		# مها still sees it in the queue, marked taken by آية, and cannot take or open it (SP-35)
		row = next(r for r in as_user(self.maha, get_queue, "All") if r.name == self.old.name)
		self.assertEqual(row["taken_by"], get_fullname(self.aya))
		self.assertFalse(row["can_take"])
		self.assertFalse(row["can_open"])
		mine = next(r for r in as_user(self.aya, get_queue, "All") if r.name == self.old.name)
		self.assertTrue(mine["can_open"])
		new = next(r for r in as_user(self.maha, get_queue, "All") if r.name == self.new.name)
		self.assertTrue(new["can_take"])

	def test_others_see_only_their_cases(self):
		camelia = make_user("sp.queue.reader@example.com", ("customer_followup",))
		self.assertNotIn(self.old.name, [r.name for r in as_user(camelia, get_queue, "All")])

	def test_taking_closes_the_pool_tasks(self):
		for user in (self.aya, self.maha):
			frappe.get_doc(
				{
					"doctype": "SP Task",
					"subject": "pool",
					"task_type": "Quote Request",
					"assigned_to": user,
					"reference_doctype": "SP Case",
					"reference_name": self.old.name,
				}
			).insert(ignore_permissions=True)
		as_user(self.aya, take, self.old.name)
		tasks = dict(
			frappe.get_all(
				"SP Task",
				{"reference_name": self.old.name, "task_type": "Quote Request"},
				["assigned_to", "status"],
				as_list=True,
			)
		)
		self.assertEqual(tasks, {self.aya: "Open", self.maha: "Cancelled"})

	def test_taking_without_a_pool_task_gives_one(self):
		as_user(self.aya, take, self.new.name)
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{"reference_name": self.new.name, "assigned_to": self.aya, "status": "Open"},
			)
		)

	def test_cannot_take_a_taken_request(self):
		as_user(self.aya, take, self.old.name)
		with self.assertRaises(frappe.ValidationError):
			as_user(self.aya, take, self.old.name)

	def test_sent_requests_leave_the_queue(self):
		for status in ("Draft", "Sent to customer"):
			self.new.status = status
			self.new.save()
		self.assertNotIn(self.new.name, [r.name for r in get_queue("All")])

	def test_page_roles(self):
		roles = {r.role for r in frappe.get_doc("Page", "sp-quote-queue").roles}
		self.assertEqual(roles, {"SP Quote Creator", "SP Followup All", "SP Admin", "System Manager"})


class TestQueueColumns(IntegrationTestCase):
	def test_key_data_and_missing_fields(self):
		from smart_power.sp_sales.quote_request import summarize_request

		pump = summarize_request("System Type-PUMP", {"hp": 5, "well_depth_m": 60})
		self.assertEqual(len(pump["key_data"]), 2)
		self.assertEqual(len(pump["missing_fields"]), 2)
		hybrid = summarize_request("System Type-HYBRID", {}, load_count=0)
		self.assertEqual(len(hybrid["missing_fields"]), 1)
		self.assertEqual(summarize_request("System Type-HYBRID", {}, load_count=3)["missing_fields"], [])

	def test_queue_rows_carry_the_columns(self):
		aya = make_user("sp.queue.cols@example.com", ("quote_creator",))
		case = make_case(system_types=[{"system_type": "System Type-ONGRID"}])
		row = next(r for r in as_user(aya, get_queue, "All") if r.name == case.name)
		self.assertEqual(row["follow_up_owner_name"], get_fullname(case.follow_up_owner))
		self.assertEqual(len(row["missing_fields"]), 1)  # no kW given
		self.assertNotIn("request_details", row)


class TestQueueActions(IntegrationTestCase):
	def setUp(self):
		self.aya = make_user("sp.qa.aya@example.com", ("quote_creator",))
		self.maha = make_user("sp.qa.maha@example.com", ("quote_creator",))
		self.camelia = make_user("sp.qa.camelia@example.com", ("lead_intake", "customer_followup"))
		self.mostafa = make_user("sp.qa.mostafa@example.com", ("installation_manager",))
		self.case = make_case(requested_by=self.camelia)

	def test_ask_missing_data_comments_and_tells_the_requester(self):
		from smart_power.sp_sales.quote_queue import ask_missing_data

		as_user(self.aya, ask_missing_data, self.case.name, "عمق البئر؟")
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{"reference_name": self.case.name, "comment_type": "Comment", "content": "عمق البئر؟"},
			)
		)
		self.assertTrue(
			frappe.db.exists("Notification Log", {"document_name": self.case.name, "for_user": self.camelia})
		)

	def test_only_quote_creators_and_not_on_a_colleagues_request(self):
		from smart_power.sp_sales.quote_queue import ask_missing_data, ask_site_survey

		with self.assertRaises(frappe.PermissionError):
			as_user(self.camelia, ask_site_survey, self.case.name)
		as_user(self.aya, take, self.case.name)
		with self.assertRaises(frappe.PermissionError):
			as_user(self.maha, ask_missing_data, self.case.name, "?")

	def test_ask_site_survey_once(self):
		from smart_power.sp_sales.quote_queue import ask_site_survey

		self.assertGreaterEqual(as_user(self.aya, ask_site_survey, self.case.name), 1)
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{
					"reference_name": frappe.db.get_value("SP Site Survey", {"case": self.case.name}),
					"task_type": "Site Survey",
					"assigned_to": self.mostafa,
				},
			)
		)
		with self.assertRaises(frappe.ValidationError):
			as_user(self.aya, ask_site_survey, self.case.name)

	def test_start_quote_takes_the_request_and_prefills(self):
		from smart_power.sp_sales.quote_queue import start_quote

		result = as_user(self.aya, start_quote, self.case.name)
		draft = frappe.get_doc("Quotation", result["quotation"])
		self.assertEqual(
			(draft.party_name, draft.sp_case, draft.docstatus), (self.case.customer, self.case.name, 0)
		)
		self.assertEqual(frappe.db.get_value("SP Case", self.case.name, "quote_creator"), self.aya)

	def test_start_quote_opens_the_draft(self):
		from smart_power.sp_sales.quote_queue import start_quote
		from smart_power.tests.utils import make_quotation, make_test_case

		case = make_test_case()
		as_user(self.aya, take, case)
		draft = make_quotation(case=case)
		self.assertEqual(as_user(self.aya, start_quote, case), {"quotation": draft.name})
