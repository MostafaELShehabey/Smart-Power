"""Optional lines under a quote's total (SP-59): own price, never in the total, cost or margin."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.permissions import get_quote_view
from smart_power.sp_sales.quotation import new_version
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user

load_erpnext_test_data()

STAINLESS = {"item_code": "_Test Item", "qty": 1, "rate": 9000, "sp_cost": 7000, "note": "موتور استانلس كامل"}


def quote_with_optional(**kw):
	q = make_quotation(save=False, **kw)
	q.append("sp_optional_lines", dict(STAINLESS))
	return q.insert()


class TestQuoteOptionalLines(IntegrationTestCase):
	def test_optional_line_stays_out_of_the_total_cost_and_margin(self):
		plain = make_quotation()
		with_optional = quote_with_optional()
		self.assertEqual(with_optional.grand_total, plain.grand_total)
		self.assertEqual(with_optional.sp_total_cost, plain.sp_total_cost)
		self.assertEqual(with_optional.sp_margin_pct, plain.sp_margin_pct)
		row = with_optional.sp_optional_lines[0]
		self.assertEqual((row.amount, row.item_name), (9000, "_Test Item"))

	def test_total_is_the_sum_of_the_non_optional_lines(self):
		q = quote_with_optional()
		self.assertEqual(q.net_total, sum(row.amount for row in q.items))

	def test_amount_follows_qty_and_rate(self):
		q = quote_with_optional()
		q.sp_optional_lines[0].qty = 2
		q.save()
		self.assertEqual(q.sp_optional_lines[0].amount, 18000)

	def test_new_version_keeps_the_optional_lines(self):
		q = quote_with_optional()
		copy = frappe.get_doc("Quotation", new_version(q.name))
		self.assertEqual([r.note for r in copy.sp_optional_lines], [STAINLESS["note"]])

	def test_sales_see_no_cost_on_optional_lines(self):
		q = quote_with_optional()
		user = make_user("sp.opt.followup@example.com", ("customer_followup",), extra_roles=("Sales User",))
		frappe.set_user(user)
		try:
			frappe.share.add("Quotation", q.name, user, read=1, flags={"ignore_share_permission": True})
			view = get_quote_view(q.name)
		finally:
			frappe.set_user("Administrator")
		self.assertNotIn("sp_cost", view["sp_optional_lines"][0])
		self.assertEqual(view["sp_optional_lines"][0]["amount"], 9000)

	def test_print_partial_lists_them_under_the_total(self):
		q = quote_with_optional()
		html = frappe.render_template(
			'{% include "smart_power/templates/print/quote_optional_lines.html" %}', {"doc": q}
		)
		self.assertIn(STAINLESS["note"], html)
		self.assertIn("9,000.00", html)
		self.assertNotIn("7,000", html)  # never the cost
		self.assertEqual(
			frappe.render_template(
				'{% include "smart_power/templates/print/quote_optional_lines.html" %}',
				{"doc": make_quotation()},
			).strip(),
			"",
		)
