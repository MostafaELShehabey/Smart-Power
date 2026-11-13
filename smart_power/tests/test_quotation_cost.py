"""Cost and profit on a case's quote (SP-54)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_stock.prices import COST, set_price
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import make_quotation


class TestQuotationCost(IntegrationTestCase):
	def setUp(self):
		set_price("_Test Item", COST, 700, supplier="_Test Supplier", reason="SP-54 test")
		self.case = case_for_test_customer()

	def test_cost_comes_from_p1_and_profit_follows(self):
		q = quote_for(self.case, rate=1000)
		row = q.items[0]
		self.assertEqual(flt(row.sp_cost), 700)
		self.assertEqual(flt(row.sp_line_profit), flt(row.net_amount) - 700)
		self.assertEqual(flt(q.sp_total_cost), 700)
		self.assertEqual(flt(q.sp_profit), flt(q.net_total) - 700)
		self.assertAlmostEqual(
			flt(q.sp_margin_pct), (flt(q.net_total) - 700) / flt(q.net_total) * 100, places=2
		)

	def test_a_cost_typed_by_hand_is_kept(self):
		q = make_quotation(save=False, rate=1000)
		q.sp_case = self.case.name
		q.items[0].sp_cost = 650
		q.insert()
		self.assertEqual(flt(q.items[0].sp_cost), 650)

	def test_quotes_without_a_case_are_left_alone(self):
		q = make_quotation(rate=1000)
		self.assertFalse(flt(q.items[0].sp_cost))
		self.assertFalse(flt(q.sp_total_cost))
