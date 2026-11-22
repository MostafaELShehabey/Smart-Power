"""Internal invoices (SP-125): one yearly series, cancelled only with a reason, printed on request."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_datetime

from smart_power.sp_finance import invoices as inv
from smart_power.sp_stations.close import INVOICE_SERIES
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY, CUSTOMER, ITEM, RATE = "_Test Company", "_Test Customer", "_Test Item", 1000


def invoice(submit=True):
	doc = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": COMPANY,
			"customer": CUSTOMER,
			"currency": frappe.get_cached_value("Company", COMPANY, "default_currency"),
			"conversion_rate": 1,
			"items": [{"item_code": ITEM, "qty": 1, "rate": RATE}],
		}
	).insert()
	if submit:
		doc.submit()
	return doc


class InvoiceCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		inv.ensure_default_series()
		cls.admin = make_user("sp.inv.admin@example.com", ("admin",))
		cls.accountant = make_user("sp.inv.accountant@example.com", ("accountant",))
		cls.clerk = make_user("sp.inv.clerk@example.com", ("lead_intake",))

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")


class TestYearlySeries(InvoiceCase):
	def test_the_first_invoice_of_2027_and_of_2028_are_both_number_0001(self):
		for year in (2027, 2028):
			frappe.db.delete("Series", {"name": f"SINV-{year}-"})
		names = []
		for day in ("2027-01-05 10:00:00", "2028-01-05 10:00:00"):
			with patch("erpnext.accounts.utils.now_datetime", return_value=get_datetime(day)):
				names.append(invoice(submit=False).name)
		self.assertEqual(names, ["SINV-2027-0001", "SINV-2028-0001"])
		self.assertEqual(frappe.get_meta("Sales Invoice").get_field("naming_series").default, INVOICE_SERIES)


class TestCancel(InvoiceCase):
	def test_a_cancelled_invoice_keeps_its_number_and_its_reason_is_reviewed(self):
		doc = invoice()
		with self.assertRaises(frappe.ValidationError):  # the plain Cancel asks for the reason
			doc.cancel()
		with self.assertRaises(frappe.PermissionError):  # the accountant does not cancel
			self.as_user(self.accountant, inv.cancel_invoice, doc.name, "خطأ في العميل")
		self.as_user(self.admin, inv.cancel_invoice, doc.name, "خطأ في العميل")
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, "docstatus"), 2)
		self.assertNotEqual(invoice(submit=False).name, doc.name)  # the number is never reused
		item = frappe.db.get_value(
			"SP Review Item", {"reference_name": doc.name, "category": inv.CATEGORY}, "summary"
		)
		self.assertIn("خطأ في العميل", item)


class TestPrint(InvoiceCase):
	def test_the_accountant_prints_for_a_bank_and_the_log_says_who_when_and_for_whom(self):
		doc = invoice()
		self.as_user(self.accountant, inv.print_invoice, doc.name, "Bank", "بنك مصر")
		log = self.as_user(self.admin, inv.print_log, doc.name)
		self.assertEqual(
			(log[0]["user"], log[0]["for_kind"], log[0]["whom"]), (self.accountant, "Bank", "بنك مصر")
		)
		self.assertTrue(log[0]["at"])
		with self.assertRaises(frappe.MandatoryError):  # which bank
			self.as_user(self.accountant, inv.print_invoice, doc.name, "Bank")
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.clerk, inv.print_invoice, doc.name, "Customer")
