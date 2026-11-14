"""Discounts on a quote (SP-68): total and section discounts, the last-minute ask, limits."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_core.documents import seed_quote_template
from smart_power.sp_quotes.discounts import discount_options, give_discount
from smart_power.sp_quotes.quote_send import send_quote
from smart_power.tests.test_quote_send import blank_pdf
from smart_power.tests.utils import (
	load_erpnext_test_data,
	make_quotation,
	make_user,
	set_setting,
)

load_erpnext_test_data()


class TestDiscounts(IntegrationTestCase):
	def setUp(self):
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		seed_quote_template()
		set_setting(followup_discount_max_pct=2, creator_discount_max_pct=4, margin_ranges=[])
		self.owner = make_user("sp.disc.owner@example.com", ("customer_followup",))
		self.admin = make_user("sp.disc.admin@example.com", ("admin",))
		q = make_quotation(save=False, rate=1000)
		q.items[0].update({"sp_line_section": "Energy", "sp_cost": 500})
		q.append(
			"items",
			{
				"item_code": "_Test Item 2",
				"qty": 1,
				"rate": 3000,
				"sp_line_section": "Submersible",
				"sp_cost": 2000,
			},
		)
		q.append(
			"items",
			{
				"item_code": "_Test Item",
				"qty": 1,
				"rate": 6000,
				"sp_line_section": "Submersible",
				"sp_lock_markup": 1,
				"sp_cost": 5000,
			},
		)
		q.insert()
		self.quote = q
		self.case = q.sp_case
		frappe.db.set_value("SP Case", self.case, "follow_up_owner", self.owner)

	def tearDown(self):
		frappe.set_user("Administrator")

	def doc(self, name=None):
		return frappe.get_doc("Quotation", name or self.quote.name)

	def test_section_discount_lowers_the_net_total_and_the_margin(self):
		before = self.doc()
		result = give_discount(self.quote.name, percent=10, applies_to="Submersible", note="عميل قديم")
		after = self.doc()
		self.assertEqual(result["amount"], 900)  # 10% of the Submersible section (3000 + 6000)
		self.assertEqual(flt(after.discount_amount), 900)
		self.assertEqual(flt(after.net_total), flt(before.net_total) - 900)
		self.assertLess(flt(after.sp_margin_pct), flt(before.sp_margin_pct))
		row = after.sp_discounts[0]
		self.assertEqual((row.given_by, row.note), ("Administrator", "عميل قديم"))

	def test_last_minute_ask_adds_to_the_discount(self):
		give_discount(self.quote.name, amount=500)
		give_discount(self.quote.name, amount=250, kind="Last-minute ask", note="العشم")
		after = self.doc()
		self.assertEqual(flt(after.discount_amount), 750)
		self.assertEqual([r.kind for r in after.sp_discounts], ["Discount", "Last-minute ask"])

	def test_follow_up_owner_above_the_limit_is_saved_flagged_and_the_admin_told(self):
		frappe.set_user(self.owner)
		result = give_discount(self.quote.name, percent=5, note="طلب العميل")  # limit 2%
		frappe.set_user("Administrator")
		self.assertEqual(flt(self.doc().discount_amount), 500)
		self.assertTrue(
			frappe.db.exists(
				"SP Review Item",
				{"reference_name": result["quotation"], "category": "Discount", "status": "Open"},
			)
		)
		told = frappe.get_all(
			"Notification Log", {"document_name": self.case, "for_user": self.admin}, pluck="subject"
		)
		self.assertTrue(told)

	def test_a_sent_version_gets_a_new_version(self):
		with patch("frappe.get_print", return_value=blank_pdf()):
			send_quote(self.quote.name, channel="In person")
		result = give_discount(self.quote.name, amount=300)
		self.assertTrue(result["new_version"])
		self.assertNotEqual(result["quotation"], self.quote.name)
		self.assertEqual(flt(self.doc().discount_amount), 0)  # the sent version is unchanged
		new = self.doc(result["quotation"])
		self.assertEqual((new.docstatus, flt(new.discount_amount)), (0, 300))
		self.assertEqual(new.sp_previous_version, self.quote.name)

	def test_a_locked_line_is_never_discounted_alone(self):
		doc = self.doc()
		doc.items[2].discount_percentage = 10  # the motor line
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc = self.doc()
		doc.items[2].rate = 5500  # its price cut by hand
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		with self.assertRaises(frappe.ValidationError):
			give_discount(self.quote.name, amount=100, applies_to="Motor line")  # not a section

	def test_checks(self):
		with self.assertRaises(frappe.ValidationError):
			give_discount(self.quote.name)  # no percent, no amount
		with self.assertRaises(frappe.ValidationError):
			give_discount(self.quote.name, amount=50000)  # more than the quote
		other = make_user("sp.disc.other@example.com", ("customer_followup",))
		frappe.set_user(other)
		with self.assertRaises(frappe.PermissionError):
			give_discount(self.quote.name, amount=100)

	def test_removing_the_discounts_restores_the_total(self):
		give_discount(self.quote.name, amount=400)
		doc = self.doc()
		doc.set("sp_discounts", [])
		doc.save()
		self.assertEqual(flt(doc.discount_amount), 0)

	def test_dialog_options_show_sale_prices_only(self):
		frappe.set_user(self.owner)
		options = discount_options(self.quote.name)
		self.assertEqual(
			{s["section"]: s["total"] for s in options["sections"]}, {"Energy": 1000, "Submersible": 9000}
		)
		self.assertEqual(options["limit_pct"], 2)
		self.assertNotIn("cost", frappe.as_json(options))
