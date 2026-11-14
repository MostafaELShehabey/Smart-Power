"""F5 hand over and S4 admin reassign of a case (SP-69)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.documents import seed_quote_template
from smart_power.sp_quotes.quote_send import send_quote
from smart_power.sp_sales.board import board
from smart_power.sp_sales.case import reassign
from smart_power.sp_sales.followup import hand_over
from smart_power.tests.test_quote_send import blank_pdf
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()


def call_tasks(case):
	return frappe.get_all(
		"SP Task",
		{"reference_name": case, "task_type": "Follow-up Call", "status": "Open"},
		pluck="assigned_to",
	)


def told(case, user):
	return frappe.get_all("Notification Log", {"document_name": case, "for_user": user}, pluck="subject")


class TestHandOver(IntegrationTestCase):
	def setUp(self):
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		seed_quote_template()
		set_setting(followup_delay_days=1)
		self.camelia = make_user(
			"sp.ho.camelia@example.com", ("lead_intake", "customer_followup", "followup_all")
		)
		self.mohamed = make_user("sp.ho.mohamed@example.com", ("customer_followup",))
		self.maha = make_user("sp.ho.maha@example.com", ("marketing_agent", "lead_intake", "quote_creator"))
		self.admin = make_user("sp.ho.admin@example.com", ("admin",))
		self.quote = make_quotation()
		self.case = self.quote.sp_case
		frappe.db.set_value("SP Case", self.case, "follow_up_owner", self.camelia)
		customer = frappe.db.get_value("SP Case", self.case, "customer")
		frappe.db.set_value("Customer", customer, "sp_featured", 0)  # tests share a transaction
		with patch("frappe.get_print", return_value=blank_pdf()):
			send_quote(self.quote.name, channel="In person")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_hand_over_moves_the_case_and_its_call_task(self):
		self.assertEqual(call_tasks(self.case), [self.camelia])
		frappe.set_user(self.camelia)
		hand_over(self.case, self.mohamed, "مشغولة اليوم")
		frappe.set_user(self.mohamed)
		self.assertTrue(any(c["name"] == self.case for c in board()["cards"]))
		frappe.set_user("Administrator")
		self.assertEqual(call_tasks(self.case), [self.mohamed])
		case = frappe.get_doc("SP Case", self.case)
		self.assertEqual(case.follow_up_owner, self.mohamed)
		last = case.owner_history[-1]
		self.assertEqual(
			(last.from_user, last.to_user, last.reason, last.changed_by),
			(self.camelia, self.mohamed, "مشغولة اليوم", self.camelia),
		)
		self.assertTrue(told(self.case, self.mohamed))
		self.assertEqual(frappe.db.get_value("Customer", case.customer, "sp_owner_user"), self.mohamed)
		self.assertFalse(
			frappe.db.exists("SP Review Item", {"reference_name": self.case, "category": "Reassignment"})
		)

	def test_only_the_owner_hands_over_and_only_to_follow_up(self):
		frappe.set_user(self.mohamed)  # not his case
		with self.assertRaises(frappe.PermissionError):
			hand_over(self.case, self.mohamed)
		frappe.set_user(self.camelia)
		with self.assertRaises(frappe.ValidationError):
			hand_over(self.case, self.maha)  # marketing does not follow customers up

	def test_marketing_cannot_hand_over(self):
		frappe.set_user("Administrator")
		frappe.db.set_value("SP Case", self.case, "follow_up_owner", self.maha)
		frappe.set_user(self.maha)
		with self.assertRaises(frappe.PermissionError):
			hand_over(self.case, self.mohamed)

	def test_admin_reassign_tells_both_and_is_reviewed(self):
		frappe.set_user(self.admin)
		reassign(self.case, "follow_up_owner", self.mohamed, "إجازة")
		frappe.set_user("Administrator")
		self.assertTrue(told(self.case, self.mohamed))
		self.assertTrue(told(self.case, self.camelia))
		case = frappe.get_doc("SP Case", self.case)
		self.assertEqual(case.owner_history[-1].reason, "إجازة")
		self.assertEqual(call_tasks(self.case), [self.mohamed])
		self.assertTrue(
			frappe.db.exists("SP Review Item", {"reference_name": self.case, "category": "Reassignment"})
		)

	def test_a_featured_customer_keeps_its_owner(self):
		customer = frappe.db.get_value("SP Case", self.case, "customer")
		frappe.db.set_value("Customer", customer, {"sp_featured": 1, "sp_owner_user": self.camelia})
		frappe.set_user(self.camelia)
		hand_over(self.case, self.mohamed)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Customer", customer, "sp_owner_user"), self.camelia)

	def test_the_dialog_offers_the_other_follow_up_people(self):
		from smart_power.sp_sales.followup import hand_over_options

		frappe.set_user(self.camelia)
		users = [u["value"] for u in hand_over_options(self.case)["users"]]
		self.assertIn(self.mohamed, users)
		self.assertNotIn(self.camelia, users)
		self.assertNotIn(self.maha, users)
		frappe.set_user(self.mohamed)
		frappe.db.set_value("SP Case", self.case, "requested_by", self.mohamed)  # he may read it
		self.assertFalse(hand_over_options(self.case)["allowed"])
