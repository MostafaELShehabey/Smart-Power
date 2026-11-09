"""SP-128 acceptance criteria on real Quotations: discount limits per role and quote validity."""

import erpnext.tests.utils  # (bootstraps ERPNext's test company, customer and item)
import frappe
from frappe.tests import IntegrationTestCase

from smart_power.rules import BLOCK, OFF, WARN, RuleBlocked
from smart_power.tests.utils import make_quotation, make_user, set_rule, set_setting


class TestDiscountRules(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.camelia = make_user("sp.followup@example.com", ("lead_intake", "customer_followup"))
		cls.aya = make_user("sp.creator@example.com", ("quote_creator",))
		cls.owner = make_user("sp.admin@example.com", ("admin",))

	def setUp(self):
		set_setting(
			followup_discount_max_pct=2, creator_discount_max_pct=4, validity_days=3, max_validity_days=0
		)
		set_rule("discount_followup_max", BLOCK)
		set_rule("discount_creator_max", WARN, warn_needs_reason=0)
		set_rule("quote_validity", BLOCK)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.after_rollback.reset()

	def test_followup_owner_blocked_above_limit(self):
		"""Given discount_followup_max = 2% at Block, when Camelia tries 2.5%, then it is blocked."""
		frappe.set_user(self.camelia)
		with self.assertRaises(RuleBlocked):
			make_quotation(discount_pct=2.5)

	def test_admin_raises_the_limit_and_the_same_discount_passes(self):
		"""Given the admin changes the limit to 3%, when she tries 2.5%, then it is allowed."""
		set_setting(followup_discount_max_pct=3)
		frappe.set_user(self.camelia)
		q = make_quotation(discount_pct=2.5)
		self.assertTrue(q.name)

	def test_followup_owner_within_limit(self):
		frappe.set_user(self.camelia)
		self.assertTrue(make_quotation(discount_pct=1.5).name)

	def test_unchanged_discount_does_not_block_a_later_save(self):
		frappe.set_user(self.aya)
		q = make_quotation(discount_pct=3)
		frappe.set_user(self.camelia)
		q.reload()
		q.order_type = q.order_type or "Sales"
		q.save()

	def test_creator_above_limit_is_flagged(self):
		frappe.set_user(self.aya)
		q = make_quotation(discount_pct=5)
		frappe.set_user("Administrator")
		hit = frappe.get_all(
			"SP Rule Hit",
			filters={"rule_key": "discount_creator_max", "reference_name": q.name},
			fields=["outcome"],
		)
		self.assertEqual([h.outcome for h in hit], ["Warned"])
		item = frappe.get_value(
			"SP Review Item",
			{"reference_name": q.name, "category": "Discount"},
			["highlight", "status"],
			as_dict=True,
		)
		self.assertEqual((item.highlight, item.status), (1, "Open"))

	def test_admin_has_no_discount_limit(self):
		frappe.set_user(self.owner)
		self.assertTrue(make_quotation(discount_pct=10).name)

	def test_rule_off_logs_nothing(self):
		set_rule("discount_creator_max", OFF)
		frappe.set_user(self.aya)
		q = make_quotation(discount_pct=5)
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("SP Rule Hit", {"reference_name": q.name}))

	def test_quote_validity_uses_the_setting(self):
		with self.assertRaises(RuleBlocked):
			make_quotation(valid_days=5)
		self.assertTrue(make_quotation(valid_days=3).name)
		set_setting(max_validity_days=7)
		self.assertTrue(make_quotation(valid_days=5).name)
