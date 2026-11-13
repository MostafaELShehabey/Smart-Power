"""Quote status, validity from the sent date, and the case's lost state (SP-54)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from smart_power.sp_core.services.lists import by_code
from smart_power.sp_sales.quotation import approve_version, expire_quotes, mark_needs_repricing, new_version
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import set_setting


def status(name):
	return frappe.db.get_value("Quotation", name, "sp_status")


class TestQuotationLifecycle(IntegrationTestCase):
	def setUp(self):
		set_setting(validity_days=3, max_validity_days=0)
		self.case = case_for_test_customer()

	def test_draft_then_sent_with_validity_from_the_sent_date(self):
		q = quote_for(self.case)
		self.assertEqual(q.sp_status, "Draft")
		frappe.db.set_value("Quotation", q.name, "transaction_date", add_days(today(), -5))
		q = frappe.get_doc("Quotation", q.name)
		q.submit()
		self.assertEqual(q.sp_status, "Sent")
		self.assertEqual(getdate(q.transaction_date), getdate(today()))
		self.assertEqual(getdate(q.valid_till), getdate(add_days(today(), 3)))

	def test_acceptance_v1_approved_v2_stays_readable(self):
		v1 = quote_for(self.case)
		v1.submit()
		v2 = frappe.get_doc("Quotation", new_version(v1.name))
		v2.submit()
		approve_version(v1.name)
		self.assertEqual((status(v1.name), status(v2.name)), ("Approved", "Sent"))
		self.assertEqual(frappe.db.get_value("Quotation", v2.name, "docstatus"), 1)

	def test_sent_version_cannot_be_edited(self):
		q = quote_for(self.case)
		q.submit()
		q.items[0].qty = 5
		with self.assertRaises(frappe.ValidationError):
			q.save()
		self.assertEqual(frappe.get_doc("Quotation", new_version(q.name)).docstatus, 0)

	def test_needs_repricing_and_expired(self):
		q = quote_for(self.case)
		q.submit()
		mark_needs_repricing(q.name, "تغير السعر")
		self.assertEqual(status(q.name), "Needs repricing")
		other = quote_for(case_for_test_customer())
		other.submit()
		frappe.db.set_value("Quotation", other.name, "valid_till", add_days(today(), -1))
		expire_quotes()
		self.assertEqual(status(other.name), "Expired")

	def test_lost_case_marks_its_quotes_lost_and_reopen_restores(self):
		q = quote_for(self.case)
		q.submit()
		self.case.reload()
		self.case.status = "Lost"
		self.case.lost_reason = by_code("Lost Reason", "PRICE_CHECK_ONLY")
		self.case.save()
		self.assertEqual(status(q.name), "Lost")
		self.case.reload()
		self.case.status = "Follow-up"
		self.case.save()
		self.assertEqual(status(q.name), "Sent")
