"""The SP Case workflow (SP-46): who moves a case to which status."""

import json
import os

import frappe
from frappe.model.workflow import apply_workflow, get_transitions
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services.lists import by_code
from smart_power.sp_sales.case_workflow import ACTIONS, STATES, WORKFLOW
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import make_user


def actions(case, user):
	"""The workflow actions a user has on the case (none if they cannot see it, SP-35)."""
	frappe.set_user(user)
	try:
		return {t.action for t in get_transitions(frappe.get_doc("SP Case", case.name))}
	except frappe.PermissionError:
		return set()
	finally:
		frappe.set_user("Administrator")


def act(case, user, action):
	frappe.set_user(user)
	try:
		return apply_workflow(frappe.get_doc("SP Case", case.name), action)
	finally:
		frappe.set_user("Administrator")


class TestCaseWorkflow(IntegrationTestCase):
	def setUp(self):
		self.owner = make_user("sp.case.owner@example.com", ("lead_intake", "customer_followup"))
		self.other_followup = make_user("sp.case.other@example.com", ("lead_intake", "customer_followup"))
		self.aya = make_user("sp.case.aya@example.com", ("quote_creator",))
		self.maha = make_user("sp.case.maha@example.com", ("quote_creator", "marketing_agent"))
		self.admin = make_user("sp.case.admin@example.com", ("admin",))

	def test_workflow_is_installed(self):
		wf = frappe.get_doc("Workflow", WORKFLOW)
		self.assertTrue(wf.is_active)
		self.assertEqual(wf.workflow_state_field, "status")
		self.assertEqual({s.state for s in wf.states}, set(STATES))
		self.assertEqual({t.action for t in wf.transitions}, set(ACTIONS))
		for state in STATES:
			self.assertTrue(frappe.db.exists("Workflow State", state))

	def test_fixture_matches_the_constants(self):
		path = os.path.join(frappe.get_app_path("smart_power"), "fixtures", "workflow.json")
		with open(path, encoding="utf-8") as f:
			wf = json.load(f)[0]
		self.assertEqual([s["state"] for s in wf["states"]], list(STATES))

	def test_happy_path(self):
		case = make_case(follow_up_owner=self.owner)
		self.assertIn("Take Request", actions(case, self.aya))
		self.assertEqual(act(case, self.aya, "Take Request").status, "Draft")
		case.reload()
		self.assertEqual(case.quote_creator, self.aya)
		self.assertEqual(case.owner_history[-1].role_kind, "Quote Creator")

		# only the case's own quote creator sends it
		self.assertNotIn("Send to Customer", actions(case, self.maha))
		act(case, self.aya, "Send to Customer")

		# only the case's follow-up owner follows up
		self.assertNotIn("Start Follow-up", actions(case, self.other_followup))
		self.assertEqual(act(case, self.owner, "Start Follow-up").status, "Follow-up")

		# won is for the admin (deposit confirmation, SP-70)
		self.assertNotIn("Mark Won", actions(case, self.owner))
		self.assertEqual(act(case, self.admin, "Mark Won").status, "Won")

	def test_revision_goes_back_to_draft(self):
		case = make_case(follow_up_owner=self.owner, quote_creator=self.aya)
		for user, action in (
			(self.aya, "Take Request"),
			(self.aya, "Send to Customer"),
			(self.owner, "Start Follow-up"),
		):
			act(case, user, action)
		self.assertEqual(act(case, self.owner, "Request Revision").status, "Draft")

	def test_lost_needs_the_reason_first_and_admin_reopens(self):
		case = make_case(follow_up_owner=self.owner)
		with self.assertRaises(frappe.MandatoryError):
			act(case, self.owner, "Mark Lost")
		frappe.db.set_value("SP Case", case.name, "lost_reason", by_code("Lost Reason", "PRICE_CHECK_ONLY"))
		self.assertEqual(act(case, self.owner, "Mark Lost").status, "Lost")
		self.assertNotIn("Reopen", actions(case, self.owner))
		self.assertEqual(act(case, self.admin, "Reopen").status, "Follow-up")

	def test_others_cannot_mark_lost(self):
		case = make_case(follow_up_owner=self.owner)
		self.assertNotIn("Mark Lost", actions(case, self.other_followup))
