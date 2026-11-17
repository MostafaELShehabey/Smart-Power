"""SP-63 margin range: the quote's project scope picks its range; out of range is an orange chip
for its creator and the admin, listed for the admin when sent, and never stops the send."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.rules.sales import margin_check, margin_onload
from smart_power.sp_quotes.quote_send import send_quote
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import make_user, set_setting

PUMP = "System Type-PUMP"
PUMP_REQUEST = {"hp": 20, "well_depth_m": 120, "water_level_m": 40, "pump_depth_m": 100}
RANGES = [
	{"scope": "Supply and install", "min_pct": 9, "max_pct": 11},
	{"scope": "Supply only", "min_pct": 6, "max_pct": 7},
]


class TestQuoteMargin(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.aya = make_user("sp.mr.aya@example.com", ("quote_creator",))
		cls.camelia = make_user("sp.mr.camelia@example.com", ("followup_all",))

	def setUp(self):
		set_setting(margin_ranges=RANGES)

	def quote(self, margin_pct, scope=None):
		case = case_for_test_customer(
			quote_creator=self.aya, system_types=[{"system_type": PUMP}], request_details=PUMP_REQUEST
		)
		q = quote_for(case)
		q.reload()
		if scope:
			q.sp_scope = scope
		# the cost that gives the wanted margin on the quote's net total
		for row in q.items:
			row.sp_cost = row.rate * (1 - margin_pct / 100)
		q.save()
		return q

	def test_supply_and_install_at_12_5_is_out_of_range(self):
		q = self.quote(12.5)
		self.assertEqual(q.sp_scope, "Supply and install")
		self.assertEqual(round(q.sp_margin_pct, 1), 12.5)
		check = margin_check(q)
		self.assertEqual((check["min"], check["max"], check["in_range"]), (9, 11, False))
		# the chip, for the quote's creator
		frappe.set_user(self.aya)
		try:
			doc = frappe.get_doc("Quotation", q.name)
			margin_onload(doc)
			self.assertFalse(doc.get_onload().get("sp_margin_check")["in_range"])
		finally:
			frappe.set_user("Administrator")
		# sent anyway, and the admin's review centre lists it
		send_quote(q.name)
		self.assertEqual(frappe.db.get_value("Quotation", q.name, "docstatus"), 1)
		self.assertTrue(
			frappe.db.exists(
				"SP Review Item", {"reference_name": q.name, "category": "Margin", "status": "Open"}
			)
		)

	def test_supply_only_reads_its_own_range(self):
		self.assertTrue(margin_check(self.quote(6.5, scope="Supply only"))["in_range"])
		self.assertFalse(margin_check(self.quote(10, scope="Supply only"))["in_range"])
		self.assertTrue(margin_check(self.quote(10))["in_range"])

	def test_follow_up_never_sees_the_margin_chip(self):
		q = self.quote(12.5)
		frappe.set_user(self.camelia)
		try:
			doc = frappe.get_doc("Quotation", q.name)
			margin_onload(doc)
			self.assertIsNone(doc.get_onload().get("sp_margin_check"))
		finally:
			frappe.set_user("Administrator")
