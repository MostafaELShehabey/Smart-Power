"""The rules engine: Off, Warn, Block, reasons, overrides and logging (SP-128)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power import rules
from smart_power.rules import BLOCK, OFF, WARN, Finding, RuleBlocked, RuleReasonRequired, rule
from smart_power.tests.utils import make_user, set_rule

KEY = "sp_test_todo_rule"
NEVER_BLOCK_KEY = "sp_test_never_block"


def _register():
	@rule(KEY, doctypes=("ToDo",), title="Test rule on ToDo", default_level=WARN)
	def _fires_on_trigger(doc, ctx):
		if "TRIGGER" in (doc.description or ""):
			return Finding(message=f"triggered with limit {ctx.limits.get('limit')}", amount=5)
		return None

	@rule(NEVER_BLOCK_KEY, doctypes=("Note",), title="Never blocks", default_level=WARN, never_block=True)
	def _never(doc, ctx):
		return None


class TestRulesEngine(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_register()
		rules.sync_rule_settings()
		cls.clerk = make_user("sp.clerk@example.com", ("customer_followup",))
		cls.admin = make_user("sp.owner@example.com", ("admin",))

	@classmethod
	def tearDownClass(cls):
		rules.unregister(KEY)
		rules.unregister(NEVER_BLOCK_KEY)
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.after_rollback.reset()
		rules.clear_cache()

	def _todo(self, text="TRIGGER", reasons=None):
		doc = frappe.get_doc({"doctype": "ToDo", "description": text})
		if reasons:
			doc.flags.sp_rule_reasons = reasons
		return doc.insert(ignore_permissions=True)

	def _hits(self, name):
		return frappe.get_all(
			"SP Rule Hit",
			filters={"rule_key": KEY, "reference_name": name},
			fields=["outcome", "reason", "level"],
		)

	def test_sync_creates_setting_with_default_level(self):
		row = frappe.get_doc("SP Rule Setting", KEY)
		self.assertEqual(row.level, WARN)
		self.assertEqual(row.applies_to, "ToDo")

	def test_off_does_nothing(self):
		set_rule(KEY, OFF)
		todo = self._todo()
		self.assertEqual(self._hits(todo.name), [])

	def test_untriggered_rule_passes(self):
		set_rule(KEY, BLOCK)
		todo = self._todo("all good")
		self.assertEqual(self._hits(todo.name), [])

	def test_warn_logs_hit_and_review_item(self):
		set_rule(KEY, WARN, warn_needs_reason=0, limits='{"limit": 7}')
		todo = self._todo()
		hits = self._hits(todo.name)
		self.assertEqual([h.outcome for h in hits], ["Warned"])
		item = frappe.get_all(
			"SP Review Item",
			filters={"reference_doctype": "ToDo", "reference_name": todo.name, "status": "Open"},
			fields=["category", "summary", "amount"],
		)
		self.assertEqual(len(item), 1)
		self.assertEqual(item[0].summary, "triggered with limit 7")

	def test_repeated_save_keeps_one_open_review_item(self):
		set_rule(KEY, WARN, warn_needs_reason=0)
		todo = self._todo()
		todo.save(ignore_permissions=True)
		count = frappe.db.count("SP Review Item", {"reference_doctype": "ToDo", "reference_name": todo.name})
		self.assertEqual(count, 1)
		self.assertEqual(len(self._hits(todo.name)), 1)

	def test_warn_with_reason_required(self):
		set_rule(KEY, WARN, warn_needs_reason=1)
		with self.assertRaises(RuleReasonRequired):
			self._todo()
		todo = self._todo(reasons={KEY: "customer is a repeat buyer"})
		self.assertEqual(self._hits(todo.name)[0].reason, "customer is a repeat buyer")

	def test_block_refuses_save(self):
		set_rule(KEY, BLOCK)
		frappe.set_user(self.clerk)
		with self.assertRaises(RuleBlocked):
			self._todo()

	def test_block_hit_is_written_after_the_rollback(self):
		set_rule(KEY, BLOCK)
		frappe.set_user(self.clerk)
		frappe.db.after_rollback.reset()
		with self.assertRaises(RuleBlocked):
			doc = frappe.get_doc({"doctype": "ToDo", "description": "TRIGGER"})
			doc.insert(ignore_permissions=True)
		queued = list(frappe.db.after_rollback._functions)
		self.assertEqual(len(queued), 1)
		frappe.set_user("Administrator")
		queued[0].func(*queued[0].args, commit=False)
		self.assertEqual([h.outcome for h in self._hits(doc.name)], ["Blocked"])

	def test_block_reason_from_non_admin_is_not_an_override(self):
		set_rule(KEY, BLOCK)
		frappe.set_user(self.clerk)
		with self.assertRaises(RuleBlocked):
			self._todo(reasons={KEY: "please"})

	def test_admin_overrides_block_with_reason(self):
		set_rule(KEY, BLOCK)
		frappe.set_user(self.admin)
		with self.assertRaises(RuleBlocked):
			self._todo()
		todo = self._todo(reasons={KEY: "approved by phone"})
		frappe.set_user("Administrator")
		self.assertEqual(self._hits(todo.name)[0].outcome, "Overridden")
		log = frappe.get_all(
			"SP Rule Override Log", filters={"reference_name": todo.name}, fields=["user", "reason"]
		)
		self.assertEqual(log[0].user, self.admin)
		self.assertEqual(log[0].reason, "approved by phone")
		self.assertTrue(
			frappe.db.exists("SP Review Item", {"reference_name": todo.name, "category": "Override"})
		)

	def test_never_block_rule_cannot_be_set_to_block(self):
		row = frappe.get_doc("SP Rule Setting", NEVER_BLOCK_KEY)
		self.assertTrue(row.never_block)
		row.level = BLOCK
		with self.assertRaises(frappe.ValidationError):
			row.save()

	def test_limits_must_be_a_json_object(self):
		row = frappe.get_doc("SP Rule Setting", KEY)
		row.limits = "[1, 2]"
		with self.assertRaises(frappe.ValidationError):
			row.save()
		row.limits = "{not json"
		with self.assertRaises(frappe.ValidationError):
			row.save()

	def test_sync_keeps_admin_level(self):
		set_rule(KEY, OFF)
		rules.sync_rule_settings()
		self.assertEqual(frappe.db.get_value("SP Rule Setting", KEY, "level"), OFF)

	def test_rule_hits_are_append_only(self):
		set_rule(KEY, WARN, warn_needs_reason=0)
		todo = self._todo()
		name = frappe.db.get_value("SP Rule Hit", {"reference_name": todo.name})
		hit = frappe.get_doc("SP Rule Hit", name)
		hit.reason = "changed"
		with self.assertRaises(frappe.ValidationError):
			hit.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			hit.delete(ignore_permissions=True)
