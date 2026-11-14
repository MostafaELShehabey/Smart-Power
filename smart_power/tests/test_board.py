"""F1 follow-up board (SP-66): who sees what, guarded moves, expiry chip, won dialog."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now_datetime, today

from smart_power.sp_core.documents import seed_quote_template
from smart_power.sp_quotes.quote_send import send_quote
from smart_power.sp_sales.board import _expiry, board, mark_won, move_case, won_options
from smart_power.sp_sales.followup import log_call
from smart_power.tests.test_quote_send import blank_pdf
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()


def card(result, case):
	return next((c for c in result["cards"] if c["name"] == case), None)


class TestBoard(IntegrationTestCase):
	def setUp(self):
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		seed_quote_template()
		set_setting(followup_delay_days=1)
		self.owner = make_user("sp.board.owner@example.com", ("customer_followup",))
		self.other = make_user("sp.board.other@example.com", ("customer_followup",))
		self.lead = make_user("sp.board.lead@example.com", ("customer_followup", "followup_all"))
		self.quote = make_quotation(valid_days=3)
		self.case = self.quote.sp_case
		frappe.db.set_value("SP Case", self.case, "follow_up_owner", self.owner)
		with patch("frappe.get_print", return_value=blank_pdf()):
			send_quote(self.quote.name, channel="In person")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_owner_sees_only_their_cases_and_the_lead_sees_all(self):
		frappe.set_user(self.other)
		self.assertIsNone(card(board(), self.case))
		frappe.set_user(self.owner)
		mine = card(board(), self.case)
		self.assertEqual(mine["column"], "sent")
		self.assertEqual(mine["quotation"], self.quote.name)
		self.assertTrue(mine["total"])
		frappe.set_user(self.lead)
		self.assertTrue(card(board(), self.case))
		self.assertIsNone(card(board({"owner": self.other}), self.case))

	def test_a_sent_card_cannot_go_back_to_waiting(self):
		frappe.set_user(self.owner)
		mine = card(board(), self.case)
		self.assertNotIn("waiting", mine["moves"])
		self.assertIn("follow_up", mine["moves"])
		with self.assertRaises(frappe.ValidationError):
			move_case(self.case, "waiting")
		self.assertEqual(move_case(self.case, "follow_up"), "Follow-up")

	def test_card_shows_the_last_call_and_the_next_one(self):
		frappe.set_user(self.owner)
		next_call = add_days(now_datetime(), 2).replace(microsecond=0)
		log_call(self.case, "Call Result-INTERESTED", "مهتم", str(next_call))
		mine = card(board(), self.case)
		self.assertEqual(mine["last_call"], "مهتم")
		self.assertEqual(str(mine["next_call_at"]), str(next_call))
		self.assertEqual(mine["column"], "follow_up")

	def test_expiry_chip_is_red_under_a_day(self):
		now = frappe.utils.get_datetime(f"{today()} 04:00:00")
		self.assertEqual(_expiry(today(), "Follow-up", now)["expiry"], "red")  # 20 h left
		self.assertEqual(_expiry(add_days(today(), 2), "Follow-up", now)["expiry"], "ok")
		self.assertEqual(_expiry(add_days(today(), -1), "Follow-up", now)["expiry"], "expired")
		self.assertIsNone(_expiry(today(), "Won", now)["expiry"])

	def test_filters(self):
		self.assertTrue(card(board({"channel": "Call"}), self.case))
		self.assertIsNone(card(board({"channel": "Showroom"}), self.case))
		self.assertIsNone(card(board({"system_type": "System Type-PUMP"}), self.case))

	def test_won_through_the_dialog_approves_the_option(self):
		# the workflow lets the admin mark a case won (from Follow-up)
		move_case(self.case, "follow_up")
		self.assertEqual([q.name for q in won_options(self.case)], [self.quote.name])
		with self.assertRaises(frappe.ValidationError):
			move_case(self.case, "won")  # Won goes through its dialog
		self.assertEqual(mark_won(self.case, self.quote.name), "Won")
		self.assertEqual(frappe.db.get_value("SP Case", self.case, "accepted_quotation"), self.quote.name)
		self.assertTrue(frappe.db.get_value("Quotation", self.quote.name, "sp_is_approved"))
		self.assertFalse(  # no more sales calls on a won case
			frappe.db.exists(
				"SP Task", {"reference_name": self.case, "task_type": "Follow-up Call", "status": "Open"}
			)
		)
		self.assertIsNone(card(board(), self.case)["next_call_at"])

	def test_a_case_change_refreshes_the_boards(self):
		with patch("frappe.publish_realtime") as publish:
			move_case(self.case, "follow_up")
		events = [c.args[0] for c in publish.call_args_list]
		self.assertIn("sp_case_update", events)

	def test_the_owner_cannot_mark_won(self):
		move_case(self.case, "follow_up")
		frappe.set_user(self.owner)
		self.assertNotIn("won", card(board(), self.case)["moves"])
		with self.assertRaises(frappe.ValidationError):
			mark_won(self.case, self.quote.name)
		self.assertEqual(frappe.db.get_value("SP Case", self.case, "status"), "Follow-up")

	def test_the_board_page_is_for_the_follow_up_team(self):
		roles = {r.role for r in frappe.get_doc("Page", "sp-followup-board").roles}
		self.assertTrue({"SP Customer Followup", "SP Followup All", "SP Admin"} <= roles)
		self.assertNotIn("SP Quote Creator", roles)
