"""Quote validity from settings, and Needs Repricing (SP-54)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from smart_power.sp_sales.quotation import approve_version, mark_needs_repricing, new_version
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import make_quotation, set_setting


class TestQuotationValidity(IntegrationTestCase):
	def setUp(self):
		set_setting(validity_days=3, max_validity_days=0)
		self.case = case_for_test_customer()

	def test_valid_till_comes_from_settings(self):
		q = make_quotation(save=False)
		q.sp_case = self.case.name
		q.valid_till = None
		q.insert()
		self.assertEqual(getdate(q.valid_till), getdate(add_days(q.transaction_date, 3)))

	def test_new_version_gets_a_fresh_validity(self):
		v1 = quote_for(self.case)
		v2 = frappe.get_doc("Quotation", new_version(v1.name))
		self.assertEqual(getdate(v2.valid_till), getdate(add_days(today(), 3)))

	def test_needs_repricing_blocks_approval_until_a_new_version(self):
		v1 = quote_for(self.case)
		v1.submit()
		mark_needs_repricing(v1.name, "سعر الألواح تغير")
		with self.assertRaises(frappe.ValidationError):
			approve_version(v1.name)
		v2 = frappe.get_doc("Quotation", new_version(v1.name))
		self.assertFalse(v2.sp_needs_repricing)
		v2.submit()
		approve_version(v2.name)

	def test_expired_version_is_not_approved(self):
		q = quote_for(self.case)
		q.submit()
		frappe.db.set_value("Quotation", q.name, "valid_till", add_days(today(), -1))
		with self.assertRaises(frappe.ValidationError):
			approve_version(q.name)
