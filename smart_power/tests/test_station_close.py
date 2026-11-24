"""Close a station (SP-80): technical close with the final invoice and warranties; financial close."""

import json
from unittest.mock import patch

import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, flt, getdate, today

from smart_power.sp_core.documents import seed_warranty_template
from smart_power.sp_core.setup.seed import seed_list_values
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.cheques import mark_collected, mark_deposited
from smart_power.sp_finance.customer_payment import confirm
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_site import commissioning as com
from smart_power.sp_stations import close
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stations.station import record_write_off
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_customer_payment import account
from smart_power.tests.test_station import WRITE_OFF_MAP
from smart_power.tests.utils import (
	load_erpnext_test_data,
	make_quotation,
	make_user,
	set_setting,
	sign_contract,
)

load_erpnext_test_data()

COMPANY, STATION, ITEM = "_Test Company", "SP Station", "_Test Item"
PUMP = "System Type-PUMP"
TOTAL, PAID, WARRANTY_YEARS = 20000, 18000, 5
REASON = "العميل لن يدفع الباقي"


def receive(station, amount):
	"""A confirmed customer payment on the station, into the company's receivable (as SP-114 posts
	them), so the final invoice takes it as an advance."""
	pe = frappe.get_doc(
		{
			"doctype": "Payment Entry",
			"payment_type": "Receive",
			"company": COMPANY,
			"party_type": "Customer",
			"party": station.customer,
			"paid_from": frappe.get_cached_value("Company", COMPANY, "default_receivable_account"),
			"paid_to": "_Test Cash - _TC",
			"paid_amount": amount,
			"received_amount": amount,
			"reference_no": "SP80",
			"reference_date": today(),
			"project": station.project,
		}
	).insert()
	pe.submit()
	return pe


class TestStationClose(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_list_values()
		com.seed_commissioning_templates()
		seed_warranty_template()
		close.ensure_invoice_series()
		seed_accounts(COMPANY)
		cls.amira = make_user("sp.cl80.amira@example.com", ("project_manager",))
		cls.admin = make_user("sp.cl80.admin@example.com", ("admin",))

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_setting(account_map=[WRITE_OFF_MAP])
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)

	def station(self, paid=PAID):
		quote = make_quotation(rate=TOTAL, valid_days=3, save=False)
		quote.items[0].sp_warranty_years = WARRANTY_YEARS
		quote.insert()
		quote.submit()
		approve_version(quote.name)
		result = make_contract(quote.sp_case)
		sign_contract(result["sales_order"])
		doc = frappe.get_doc(STATION, result["station"])
		doc.set("systems", [{"system_type": PUMP, "capacity_kw": 10, "qty": 1}])
		doc.save()
		if paid:
			receive(doc, paid)
		frappe.db.set_value(
			STATION, doc.name, "status", "Installing"
		)  # on site: Close Technically is offered
		return frappe.get_doc(STATION, doc.name)

	def commission(self, station, serial="PUMP-0001", operation_date=None):
		doc = frappe.get_doc(
			{
				"doctype": "SP Commissioning",
				"station": station.name,
				"system_row": station.systems[0].name,
				"operation_date": operation_date or today(),
				"inverter_serial": "INV-0001",
				"components": [
					{"component_type": "Pump", "item": ITEM, "serial": serial, "warranty_months": 12}
				],
			}
		).insert()
		for row in doc.checklist:
			row.done = 1
		doc.save()
		doc.submit()
		return doc

	def close_technically(self, station):
		frappe.set_user(self.amira)
		try:
			return apply_workflow(frappe.get_doc(STATION, station.name), "Close Technically")
		finally:
			frappe.set_user("Administrator")

	def test_no_operation_date_refuses_the_technical_close(self):
		station = self.station()
		with self.assertRaises(frappe.ValidationError):
			self.close_technically(station)
		self.assertEqual(frappe.db.get_value(STATION, station.name, "status"), "Installing")

	def test_every_system_commissioned_and_every_serial_filled(self):
		station = self.station()
		frappe.db.set_value(STATION, station.name, "operation_date", today())
		with self.assertRaises(frappe.ValidationError):
			self.close_technically(station)  # the system is not commissioned
		self.commission(station, serial="")
		with self.assertRaises(frappe.ValidationError):
			self.close_technically(station)  # a component without its serial

	def test_the_close_makes_the_yearly_invoice_with_the_advances_and_the_quote_warranty(self):
		station = self.station()
		commissioning = self.commission(station)
		self.close_technically(station)
		station.reload()
		self.assertEqual(station.status, "Technically closed")
		invoice = frappe.get_doc("Sales Invoice", station.final_invoice)
		year = getdate(invoice.posting_date).year
		self.assertTrue(invoice.name.startswith(f"SINV-{year}-"))
		self.assertEqual(len(invoice.name.rsplit("-", 1)[1]), 4)  # its own 4-digit counter
		self.assertEqual((invoice.docstatus, invoice.project), (1, station.project))
		self.assertEqual(flt(sum(flt(a.allocated_amount) for a in invoice.advances)), PAID)
		self.assertEqual(
			{frappe.db.get_value("Payment Entry", a.reference_name, "project") for a in invoice.advances},
			{station.project},
		)  # only this station's payments, not the customer's other stations
		self.assertEqual(flt(invoice.outstanding_amount), TOTAL - PAID)
		self.assertEqual(invoice.items[0].sales_order, station.sales_order)
		component = frappe.get_doc("SP Station Component", commissioning.components[0].name)
		self.assertEqual(component.warranty_months, WARRANTY_YEARS * 12)  # the quote's years
		self.assertEqual(
			getdate(component.warranty_end), add_months(getdate(today()), WARRANTY_YEARS * 12)
		)  # the same date (owner, 2026-11-22, SP-179)
		self.assertEqual(close.final_invoice(station), invoice.name)  # once

	def test_writing_off_the_last_2000_closes_financially_with_a_review_item(self):
		station = self.station()
		self.commission(station)
		self.close_technically(station)
		frappe.set_user(self.admin)
		result = record_write_off(station.name, TOTAL - PAID, REASON)
		frappe.set_user("Administrator")
		self.assertTrue(result["financially_closed"])
		station.reload()
		self.assertEqual((station.status, str(station.fin_closed_on)), ("Financially closed", today()))
		self.assertTrue(
			frappe.db.exists("SP Review Item", {"category": "Write-off", "reference_name": station.name})
		)
		snapshot = json.loads(station.close_cost_snapshot)
		self.assertEqual(flt(snapshot["agreed"]), TOTAL)
		self.assertIn("actual", snapshot)

	def test_the_last_payment_closes_a_technically_closed_station(self):
		station = self.station()
		self.commission(station)
		self.close_technically(station)
		self.assertEqual(frappe.db.get_value(STATION, station.name, "status"), "Technically closed")
		receive(station, TOTAL - PAID)
		self.assertEqual(frappe.db.get_value(STATION, station.name, "status"), "Financially closed")

	def collect(self, station, amount):
		"""A station payment recorded and confirmed by the admin, as SP-114 posts it."""
		frappe.set_user(self.admin)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SP Customer Payment",
					"station": station.name,
					"amount": amount,
					"method": "Payment Method-CASH",
					"receiving_account": account("SP Close Bank", "Bank", "Official", account_type="Bank"),
					"reference_no": "BUG14",
					"receipt_photo": "/files/receipt.jpg",
				}
			).insert()
			doc.submit()
			confirm(doc.name)
		finally:
			frappe.set_user("Administrator")
		return frappe.get_doc("SP Customer Payment", doc.name)

	def closed_station(self):
		station = self.station()
		self.commission(station)
		self.close_technically(station)
		invoice = frappe.db.get_value(STATION, station.name, "final_invoice")
		self.assertEqual(
			flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount")), TOTAL - PAID
		)
		return station, invoice

	def references(self, payment):
		pe = frappe.get_doc("Payment Entry", payment.payment_entry)
		return [(r.reference_doctype, r.reference_name, flt(r.allocated_amount)) for r in pe.references]

	def test_a_payment_after_the_technical_close_pays_the_final_invoice(self):
		# BUG-14: the contract is fully billed by then; ERPNext refused an advance against it
		station, invoice = self.closed_station()
		part = 500
		payment = self.collect(station, part)
		self.assertEqual(payment.status, "Confirmed")
		self.assertEqual(self.references(payment), [("Sales Invoice", invoice, part)])
		self.assertEqual(
			flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount")), TOTAL - PAID - part
		)
		self.assertEqual(frappe.db.get_value(STATION, station.name, "status"), "Technically closed")
		# the rest, and more than is left: the invoice is paid and the station closes financially
		over = 100
		last = self.collect(station, TOTAL - PAID - part + over)
		self.assertEqual(self.references(last), [("Sales Invoice", invoice, TOTAL - PAID - part)])
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount")), 0)
		self.assertEqual(frappe.db.get_value(STATION, station.name, "status"), "Financially closed")

	def test_a_cheque_collected_after_the_technical_close_pays_the_final_invoice(self):
		set_setting(cheque_auto_confirm=1)
		station, invoice = self.closed_station()
		cheque = frappe.get_doc(
			{
				"doctype": "SP Cheque",
				"cheque_no": frappe.generate_hash(length=8),
				"amount": TOTAL - PAID,
				"due_date": today(),
				"bank_or_post": "مكتب بريد",
				"holder": self.admin,
				"station": station.name,
			}
		).insert()
		frappe.set_user(self.admin)
		mark_deposited(cheque.name)
		mark_collected(cheque.name)
		frappe.set_user("Administrator")
		payment = frappe.get_doc(
			"SP Customer Payment", frappe.db.get_value("SP Cheque", cheque.name, "customer_payment")
		)
		self.assertEqual(payment.status, "Confirmed")
		self.assertEqual(self.references(payment), [("Sales Invoice", invoice, TOTAL - PAID)])
		self.assertEqual(frappe.db.get_value(STATION, station.name, "status"), "Financially closed")

	def test_the_warranty_certificate_lists_the_components(self):
		station = self.station()
		self.commission(station, serial="PUMP-7788")
		self.close_technically(station)
		html = frappe.get_print(STATION, station.name, "SP Warranty Certificate")
		self.assertIn("PUMP-7788", html)
		self.assertIn("sp-block-preamble", html)  # the admin's text
