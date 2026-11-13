"""A Smart Power quote belongs to its SP Case (SP-54)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.tests.test_case import make_case
from smart_power.tests.utils import load_erpnext_test_data, make_customer, make_quotation

load_erpnext_test_data()


def case_for_test_customer(**kw):
	return make_case(customer="_Test Customer", **kw)


def quote_for(case, **kw):
	q = make_quotation(save=False, **kw)
	q.sp_case = case.name
	return q.insert()


class TestQuotationCase(IntegrationTestCase):
	def test_quote_for_the_case_customer(self):
		case = case_for_test_customer()
		frappe.db.set_value(
			"SP Case", case.name, "last_action_at", "2026-01-01 00:00:00", update_modified=False
		)
		q = quote_for(case)
		self.assertEqual(q.sp_case, case.name)
		self.assertGreater(str(frappe.db.get_value("SP Case", case.name, "last_action_at")), "2026-11")

	def test_wrong_customer_is_refused(self):
		case = make_case(customer=make_customer("01009990301", "عميل آخر"))
		with self.assertRaises(frappe.ValidationError):
			quote_for(case)

	def test_quotes_without_a_case_still_work(self):
		self.assertFalse(make_quotation().sp_case)

	def test_case_shows_its_quotes(self):
		links = frappe.get_meta("SP Case").links
		self.assertIn(("Quotation", "sp_case"), {(link.link_doctype, link.link_fieldname) for link in links})
