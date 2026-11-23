"""X5 Workflows (SP-133): seeded once and the admin's kept; the guard keeps what the code needs;
a new state goes before a state the system sets; the code-driven records are read-only."""

import frappe
from frappe.model.workflow import apply_workflow, get_transitions
from frappe.tests import IntegrationTestCase

from smart_power.sp_core import workflows as wf
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

CASE, STATION = "SP Case", "SP Station"
WAITING, ASK, SIGNED = "Waiting customer signature", "Ask for Signature", "Signature Received"


def master(doctype, field, name):
	if not frappe.db.exists(doctype, name):
		frappe.get_doc({"doctype": doctype, field: name}).insert(ignore_permissions=True)


class TestWorkflows(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wf.seed_workflows()
		master("Workflow State", "workflow_state_name", WAITING)
		for action in (ASK, SIGNED, "Skip to Won"):
			master("Workflow Action Master", "workflow_action_name", action)
		cls.owner = make_user("sp.wf.owner@example.com", ("customer_followup",))
		cls.amira = make_user("sp.wf.amira@example.com", ("contract_manager", "project_manager"))
		cls.admin = make_user("sp.wf.admin@example.com", ("admin",))

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def workflow(self, name=CASE):
		return frappe.get_doc("Workflow", name)

	def test_seeding_creates_only_what_is_missing(self):
		self.assertEqual(wf.seed_workflows(), [])
		doc = self.workflow()
		doc.append("states", {"state": WAITING, "doc_status": "0", "allow_edit": "Desk User"})
		doc.save()
		wf.seed_workflows()
		self.assertIn(WAITING, [s.state for s in self.workflow().states])  # the admin's state stays

	def test_waiting_for_signature_goes_before_won(self):
		doc = self.workflow()
		doc.append("states", {"state": WAITING, "doc_status": "0", "allow_edit": "Desk User"})
		doc.append(
			"transitions",
			{"state": "Follow-up", "action": ASK, "next_state": WAITING, "allowed": "SP Customer Followup"},
		)
		doc.append(
			"transitions",
			{"state": WAITING, "action": SIGNED, "next_state": "Follow-up", "allowed": "SP Contract Manager"},
		)
		doc.save()
		case = make_case(follow_up_owner=self.owner)
		frappe.db.set_value(CASE, case.name, "status", "Follow-up")
		frappe.set_user(self.owner)
		moved = apply_workflow(frappe.get_doc(CASE, case.name), ASK)
		self.assertEqual(moved.status, WAITING)  # the follow-up owner sees the new status
		# the admin lets أميرة's role open cases in the permissions matrix (SP-131); the contracts team
		# reads a case once a version is approved (SP-35)
		from smart_power.sp_core.permissions_matrix import save

		frappe.set_user("Administrator")
		save("SP Contract Manager", {CASE: {"view": True}})
		frappe.db.set_value(CASE, case.name, "accepted_quotation", "SP133-QUOTE", update_modified=False)
		frappe.set_user(self.amira)
		doc = frappe.get_doc(CASE, case.name)
		self.assertIn(SIGNED, [t.action for t in get_transitions(doc)])  # أميرة moves it on
		self.assertIn(WAITING, frappe.get_meta(CASE).get_field("status").options.split("\n"))
		frappe.set_user("Administrator")
		frappe.get_doc(CASE, case.name).db_set("status", "Won")  # as the confirmed deposit does

	def test_a_core_state_cannot_be_removed(self):
		doc = self.workflow()
		doc.states = [s for s in doc.states if s.state != "Won"]
		with self.assertRaises(frappe.ValidationError) as refused:
			doc.save()
		self.assertIn("core system state", str(refused.exception))
		frappe.local.lang = "ar"
		self.addCleanup(setattr, frappe.local, "lang", "en")
		self.assertIn("حالة أساسية للنظام", wf._core("Won"))  # the story's message

	def test_the_steps_around_system_states_are_kept(self):
		doc = self.workflow()
		doc.append("states", {"state": WAITING, "doc_status": "0", "allow_edit": "Desk User"})
		doc.append(
			"transitions", {"state": "Won", "action": ASK, "next_state": WAITING, "allowed": "SP Admin"}
		)
		self.assertRaises(frappe.ValidationError, doc.save)  # nothing after Won
		doc = self.workflow()
		doc.append(
			"transitions",
			{"state": "Follow-up", "action": "Skip to Won", "next_state": "Won", "allowed": "SP Admin"},
		)
		self.assertRaises(frappe.ValidationError, doc.save)  # only the deposit makes a case Won
		station = self.workflow(STATION)
		station.transitions = [t for t in station.transitions if t.action != "Close Financially"]
		self.assertRaises(frappe.ValidationError, station.save)

	def test_the_code_driven_records_get_no_workflow(self):
		doc = frappe.get_doc(
			{
				"doctype": "Workflow",
				"workflow_name": "Payments",
				"document_type": "SP Customer Payment",
				"workflow_state_field": "status",
				"is_active": 1,
				"states": [{"state": "Draft", "doc_status": "0", "allow_edit": "SP Admin"}],
			}
		)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_the_lifecycles_show_their_locks(self):
		frappe.set_user(self.admin)
		keys = {f["key"]: f["editable"] for f in wf.flows()}
		self.assertTrue(keys[CASE])
		self.assertFalse(keys["SP Customer Payment"])
		case = wf.diagram(CASE)
		won = next(s for s in case["states"] if s["state"] == "Won")
		self.assertEqual((won["locked"], won["by_system"]), (True, True))
		self.assertTrue(case["transitions"])
		payment = wf.diagram("SP Customer Payment")
		self.assertIn("Confirmed", [s["state"] for s in payment["states"] if s["locked"]])
		frappe.set_user(self.owner)
		self.assertRaises(frappe.PermissionError, wf.flows)
