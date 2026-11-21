"""Instalment tracking: FIFO allocation, Overdue, the daily job and its alerts (SP-81)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_finance.balances import overdue
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations import installments
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_station import COMPANY, receive
from smart_power.tests.utils import (
	load_erpnext_test_data,
	make_quotation,
	make_user,
	set_setting,
	sign_contract,
)

load_erpnext_test_data()


class InstalmentCase(IntegrationTestCase):
	"""A station with a 20,000 contract in two instalments; shared with the CL1 tests."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		set_setting(installment_due_lead_days=3)
		self.amira = make_user("sp.cl.amira@example.com", ("project_manager",))
		self.admin = make_user("sp.cl.admin@example.com", ("admin",))
		self.station = self.contract_station()

	def tearDown(self):
		frappe.set_user("Administrator")

	def contract_station(self):
		"""A 20,000 contract in two instalments: 10,000 today and 10,000 in two days."""
		quote = make_quotation(rate=20000, valid_days=3)
		quote.submit()
		approve_version(quote.name)
		result = make_contract(quote.sp_case)
		so = frappe.get_doc("Sales Order", result["sales_order"])
		so.payment_terms_template = None
		so.set("payment_schedule", [])
		total = flt(so.rounded_total or so.grand_total)
		for days in (0, 2):
			so.append(
				"payment_schedule",
				{"due_date": add_days(today(), days), "invoice_portion": 50, "payment_amount": total / 2},
			)
		so.save()
		sign_contract(so)
		frappe.db.set_value("SP Station", result["station"], "collection_owner", self.amira)
		return frappe.get_doc("SP Station", result["station"])

	def rows(self):
		return frappe.get_all(
			"Payment Schedule",
			{"parent": self.station.sales_order},
			["name", "due_date", "payment_amount", "sp_paid_amount", "sp_status"],
			order_by="due_date asc",
		)


class TestInstallments(InstalmentCase):
	def test_10000_due_yesterday_with_4000_paid_is_overdue_6000_and_alerts_once(self):
		first = self.rows()[0]
		frappe.db.set_value("Payment Schedule", first.name, "due_date", add_days(today(), -1))
		receive(self.station, 4000)  # confirmed: the station refreshes and allocates
		installments.update_installments()
		installments.update_installments()  # the next day's run alerts nothing new
		rows = self.rows()
		self.assertEqual((rows[0].sp_status, flt(rows[0].sp_paid_amount)), ("Overdue", 4000))
		self.assertEqual(flt(rows[0].payment_amount) - flt(rows[0].sp_paid_amount), 6000)
		self.assertEqual(rows[1].sp_status, "Due")
		self.station.reload()
		self.assertEqual((flt(self.station.overdue_amount), self.station.has_overdue), (6000, 1))
		self.assertEqual(overdue(self.station), 6000)  # AR1 (SP-120) agrees
		for user in (self.amira, self.admin):
			self.assertEqual(
				frappe.db.count(
					"Notification Log",
					{"for_user": user, "document_name": self.station.name, "subject": ("like", "Overdue:%")},
				),
				1,
			)
		# due in two days, inside the 3-day lead: the owner only, once
		self.assertEqual(
			frappe.db.count(
				"Notification Log",
				{
					"for_user": self.amira,
					"document_name": self.station.name,
					"subject": ("like", "Instalment due:%"),
				},
			),
			1,
		)
		self.assertFalse(
			frappe.db.count(
				"Notification Log",
				{
					"for_user": self.admin,
					"document_name": self.station.name,
					"subject": ("like", "Instalment due:%"),
				},
			)
		)

	def test_payments_fill_the_oldest_instalment_first(self):
		receive(self.station, 13000)
		rows = self.rows()
		self.assertEqual(
			[(r.sp_status, flt(r.sp_paid_amount)) for r in rows], [("Paid", 10000), ("Due", 3000)]
		)

	def test_a_reversed_payment_reopens_the_instalment(self):
		pe = receive(self.station, 10000)
		self.assertEqual(self.rows()[0].sp_status, "Paid")
		pe.cancel()
		self.assertEqual((self.rows()[0].sp_status, flt(self.rows()[0].sp_paid_amount)), ("Due", 0))
