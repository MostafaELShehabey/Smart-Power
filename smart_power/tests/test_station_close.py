"""Close a station (SP-80): technical close with the final invoice and warranties; financial close."""

import json
from unittest.mock import patch

import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, flt, getdate, today

from smart_power.sp_core.documents import seed_warranty_template
from smart_power.sp_core.setup.seed import seed_list_values
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_site import commissioning as com
from smart_power.sp_stations import close
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stations.station import record_write_off
from smart_power.sp_stock import warehouses as wh
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
			getdate(component.warranty_end), add_days(add_months(getdate(today()), WARRANTY_YEARS * 12), -1)
		)
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

	def test_the_warranty_certificate_lists_the_components(self):
		station = self.station()
		self.commission(station, serial="PUMP-7788")
		self.close_technically(station)
		html = frappe.get_print(STATION, station.name, "SP Warranty Certificate")
		self.assertIn("PUMP-7788", html)
		self.assertIn("sp-block-preamble", html)  # the admin's text
