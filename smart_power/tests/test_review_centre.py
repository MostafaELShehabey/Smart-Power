"""RV2 Review centre (SP-129): tabs and counts, highlighted discounts, comments, bulk review."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.review_centre import (
	TABS,
	attention_count,
	comment,
	forward,
	items,
	mark_reviewed,
	raise_item,
	tabs,
)
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_rule, set_setting

load_erpnext_test_data()


class TestReviewCentre(IntegrationTestCase):
	def setUp(self):
		set_setting(followup_discount_max_pct=2, creator_discount_max_pct=4)
		set_rule("discount_creator_max", "Warn", warn_needs_reason=0)
		self.aya = make_user("sp.rv.aya@example.com", ("quote_creator",))
		self.admin = make_user("sp.rv.admin@example.com", ("admin",))

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_every_discount_is_listed_and_above_four_percent_highlighted(self):
		frappe.set_user(self.aya)
		high = make_quotation(discount_pct=5)
		low = make_quotation(discount_pct=3)
		frappe.set_user("Administrator")
		listed = {i.reference_name: i for i in items("Discount")}
		self.assertTrue(listed[high.name].highlight)
		self.assertIn(low.name, listed)  # within the limit, still listed
		self.assertFalse(listed[low.name].highlight)
		# one item per quote, even when the limit rule listed it too
		self.assertEqual(
			frappe.db.count("SP Review Item", {"reference_name": high.name, "status": "Open"}), 1
		)

	def test_a_comment_tells_the_owner_with_a_link(self):
		frappe.set_user(self.aya)
		quote = make_quotation()
		frappe.set_user("Administrator")
		item = raise_item("Margin", quote, "هامش خارج النطاق")
		to = comment(item.name, "راجعي السعر")
		self.assertEqual(to, self.aya)  # the quote's creator
		note = frappe.get_all(
			"Notification Log",
			{"for_user": self.aya, "document_type": "Quotation", "document_name": quote.name},
			pluck="subject",
		)
		self.assertTrue(any("راجعي السعر" in s for s in note))
		self.assertEqual(frappe.db.get_value("SP Review Item", item.name, "comment"), "راجعي السعر")

	def test_bulk_mark_reviewed_leaves_the_rest_and_the_attention_count(self):
		before = attention_count()
		quote = make_quotation()
		names = [
			raise_item("Abnormal", frappe._dict(doctype="SP Case", name=f"CS-RV-{i}"), "x").name
			for i in range(12)
		]
		self.assertEqual(attention_count(), before + 12)
		self.assertEqual(mark_reviewed(names[:10]), 10)
		self.assertEqual(attention_count(), before + 2)
		reviewed = frappe.get_doc("SP Review Item", names[0])
		self.assertEqual((reviewed.status, reviewed.reviewed_by), ("Reviewed", "Administrator"))
		self.assertTrue(quote.name)

	def test_tabs_and_their_counts(self):
		data = tabs()
		self.assertEqual([t["category"] for t in data["tabs"]], list(TABS))
		self.assertEqual(data["open"], attention_count())

	def test_only_the_admin_reviews_and_forwards_to_a_reviewer(self):
		frappe.set_user(self.aya)
		with self.assertRaises(frappe.PermissionError):
			tabs()
		frappe.set_user("Administrator")
		item = raise_item("Abnormal", frappe._dict(doctype="SP Case", name="CS-RV-FWD"), "x")
		with self.assertRaises(frappe.ValidationError):
			forward(item.name, self.aya)
		forward(item.name, self.admin, "راجعها")
		self.assertTrue(
			frappe.db.exists(
				"ToDo", {"reference_name": item.name, "allocated_to": self.admin, "status": "Open"}
			)
		)
