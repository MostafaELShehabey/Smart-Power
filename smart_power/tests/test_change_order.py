"""S3 Change order (SP-78): the contract, the agreed amount and the schedule take the change."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, flt, today

from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations import change_order as co
from smart_power.sp_stations.contract import freeze_estimate, make_contract
from smart_power.sp_stations.station_tabs import tab
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_station import COMPANY, receive
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, sign_contract

load_erpnext_test_data()

PANEL, OTHER = "_Test Item", "_Test Item 2"
APPROVAL = "/private/files/sp78-approval.pdf"
INSTALMENTS = 8
CHASSIS_RATE, CHASSIS_COST, MC4_RATE, MC4_COST = 60000, 46875, 50, 40


class TestChangeOrder(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		cls.amira = make_user(
			"sp.co.amira@example.com", ("contract_manager", "project_manager", "quote_creator")
		)
		cls.mostafa = make_user("sp.co.mostafa@example.com", ("installation_manager", "site_receiver"))

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def station(self, signed=True, paid=50000):
		"""A signed contract of 40 panels at 5,000 = 200,000, in 8 monthly instalments of 25,000;
		the first two are paid."""
		quote = make_quotation(rate=5000, valid_days=3, save=False)
		quote.items[0].qty = 40
		quote.insert()
		quote.submit()
		approve_version(quote.name)
		result = make_contract(quote.sp_case)
		so = frappe.get_doc("Sales Order", result["sales_order"])
		so.payment_terms_template = None
		so.set("payment_schedule", [])
		for month in range(INSTALMENTS):
			so.append(
				"payment_schedule",
				{
					"due_date": add_months(today(), month),
					"invoice_portion": 100 / INSTALMENTS,
					"payment_amount": 25000,
				},
			)
		so.save()
		if signed:
			sign_contract(so)
		station = frappe.get_doc("SP Station", result["station"])
		frappe.db.set_value(
			"SP Station",
			station.name,
			"estimated_cost_snapshot",
			json.dumps(
				{"lines": [{"item_code": PANEL, "qty": 40, "rate": 5000, "cost": 4000}], "total_cost": 160000}
			),
		)
		if paid:
			receive(station, paid)
		return frappe.get_doc("SP Station", station.name)

	def change(self, station, lines, mode=co.SPREAD, submit=True, **kw):
		def make():
			doc = frappe.get_doc(
				{
					"doctype": co.CHANGE_ORDER,
					"station": station.name,
					"reason": "طلب العميل",
					"approval_file": APPROVAL,
					"schedule_mode": mode,
					"items": [
						{"item_code": item, "qty": qty, "rate": rate, **(extra[0] if extra else {})}
						for item, qty, rate, *extra in lines
					],
					**kw,
				}
			).insert()
			if submit:
				doc.submit()
			return doc

		frappe.set_user(self.amira)
		try:
			return make()
		finally:
			frappe.set_user("Administrator")

	def schedule(self, station):
		return [
			flt(r.payment_amount)
			for r in frappe.get_all(
				"Payment Schedule",
				{"parent": station.sales_order, "parenttype": "Sales Order"},
				["payment_amount"],
				order_by="idx asc",
			)
		]

	def manual_station(self):
		"""Two manual lines of one item, as a pump quote has them: a chassis of 60,000 (cost 46,875)
		and 10 connectors at 50 (cost 40 each). The estimate is frozen as at the deposit."""
		quote = make_quotation(rate=CHASSIS_RATE, valid_days=3, save=False)
		quote.items[0].sp_cost = CHASSIS_COST
		quote.append("items", {"item_code": PANEL, "qty": 10, "rate": MC4_RATE, "sp_cost": MC4_COST})
		quote.insert()
		quote.submit()
		approve_version(quote.name)
		result = make_contract(quote.sp_case)
		so = frappe.get_doc("Sales Order", result["sales_order"])
		so.payment_terms_template = None
		so.set("payment_schedule", [])
		for month in range(2):
			so.append(
				"payment_schedule",
				{"due_date": add_months(today(), month), "invoice_portion": 50, "payment_amount": 30250},
			)
		so.save()
		sign_contract(so)
		freeze_estimate(so.name)
		station = frappe.get_doc("SP Station", result["station"])
		connectors = next(r.name for r in so.items if flt(r.rate) == MC4_RATE)
		return station, connectors

	def test_a_returned_manual_line_takes_its_own_cost_not_the_first_lines(self):
		# BUG-11: every manual line is one item; the return took the chassis's cost
		station, connectors = self.manual_station()
		frappe.set_user(self.amira)
		offered = {line["so_detail"]: line["cost"] for line in co.contract_lines(station.name)}
		frappe.set_user("Administrator")
		self.assertEqual(offered[connectors], MC4_COST)
		self.assertEqual(sorted(offered.values()), [MC4_COST, CHASSIS_COST])
		doc = self.change(station, [(PANEL, -2, 0, {"so_detail": connectors})], mode=co.REDUCE_LAST)
		self.assertEqual((flt(doc.items[0].cost), flt(doc.cost_delta)), (MC4_COST, -2 * MC4_COST))
		self.assertEqual(flt(doc.delta_amount), -2 * MC4_RATE)
		snapshot = json.loads(frappe.db.get_value("SP Station", station.name, "estimated_cost_snapshot"))
		self.assertEqual(snapshot["total_cost"], CHASSIS_COST + 8 * MC4_COST)

	def test_an_estimate_frozen_before_the_fix_matches_by_the_quotes_order(self):
		station, connectors = self.manual_station()
		snapshot = json.loads(frappe.db.get_value("SP Station", station.name, "estimated_cost_snapshot"))
		for line in snapshot["lines"]:
			line.pop("quotation_item")
		frappe.db.set_value("SP Station", station.name, "estimated_cost_snapshot", json.dumps(snapshot))
		self.assertEqual(co._snapshot_cost(frappe.get_doc("SP Station", station.name), connectors), MC4_COST)

	def test_a_line_an_earlier_change_order_added_returns_at_that_orders_cost(self):
		station = self.station()
		self.change(station, [(OTHER, 1, 12000, {"cost": 9000})])
		doc = self.change(station.reload() or station, [(OTHER, -1, 0)])
		self.assertEqual((flt(doc.items[0].cost), flt(doc.cost_delta)), (9000, -9000))

	def test_the_print_the_customer_signs_has_no_cost(self):
		"""BUG-31: the standard print showed the cost column and the contract line's id."""
		doc = self.change(self.station(), [(PANEL, -2, 0)], submit=False)
		self.assertEqual((flt(doc.items[0].cost), flt(doc.cost_delta)), (4000, -8000))
		html = frappe.get_print(co.CHANGE_ORDER, doc.name)  # as the Administrator, who sees cost
		self.assertIn("-10,000", html)  # the change the customer approves
		for internal in ("4,000", "8,000", doc.items[0].so_detail, doc.approval_file):
			self.assertFalse(internal in html, f"{internal} is on the print")

	def test_plus_12000_spread_over_the_remaining_6_raises_each_by_2000(self):
		station = self.station()
		doc = self.change(station, [(OTHER, 1, 12000)])
		station.reload()
		self.assertEqual(flt(station.agreed_amount), 212000)
		self.assertEqual(self.schedule(station), [25000, 25000] + [27000] * 6)
		self.assertEqual(
			(flt(doc.agreed_before), flt(doc.agreed_after), flt(doc.delta_amount)), (200000, 212000, 12000)
		)
		self.assertEqual(flt(station.remaining_amount), 162000)
		self.assertTrue(
			frappe.db.exists(
				"SP Review Item", {"category": "Change Order", "reference_name": doc.name, "amount": 12000}
			)
		)

	def test_a_return_of_2_panels_at_5000_is_minus_10000_and_lowers_the_remaining(self):
		station = self.station()
		doc = self.change(station, [(PANEL, -2, 4000)], mode=co.REDUCE_LAST)  # the typed rate is ignored
		self.assertEqual((flt(doc.items[0].rate), flt(doc.delta_amount)), (5000, -10000))
		station.reload()
		self.assertEqual((flt(station.agreed_amount), flt(station.remaining_amount)), (190000, 140000))
		self.assertEqual(self.schedule(station), [25000] * 7 + [15000])
		self.assertEqual(frappe.db.get_value("Sales Order Item", {"parent": station.sales_order}, "qty"), 38)
		snapshot = json.loads(station.estimated_cost_snapshot)
		self.assertEqual((snapshot["total_cost"], snapshot["change_orders"][0]["cost"]), (152000, -8000))

	def test_a_reduction_spread_comes_off_the_unpaid_instalments_only(self):
		station = self.station()
		self.change(station, [(PANEL, -6, 0)])
		self.assertEqual(self.schedule(station), [25000, 25000] + [20000] * 6)

	def test_an_addition_as_a_new_installment(self):
		station = self.station()
		day = add_days(today(), 400)
		self.change(station, [(OTHER, 1, 12000)], mode=co.NEW_INSTALLMENT, new_installment_date=day)
		self.assertEqual(self.schedule(station), [25000] * INSTALMENTS + [12000])

	def test_no_approval_file_is_refused(self):
		station = self.station()
		with self.assertRaises(frappe.MandatoryError):
			self.change(station, [(OTHER, 1, 12000)], approval_file=None)

	def test_a_reduction_larger_than_what_is_unpaid_is_refused(self):
		station = self.station(paid=195000)
		with self.assertRaises(frappe.ValidationError):
			self.change(station, [(PANEL, -2, 0)])

	def test_an_unsigned_contract_is_changed_directly_not_by_a_change_order(self):
		station = self.station(signed=False, paid=0)
		with self.assertRaises(frappe.ValidationError):
			self.change(station, [(OTHER, 1, 12000)])

	def test_more_than_is_on_the_contract_cannot_be_returned(self):
		station = self.station()
		with self.assertRaises(frappe.ValidationError):
			self.change(station, [(PANEL, -41, 0)])
		with self.assertRaises(frappe.ValidationError):
			self.change(station, [(OTHER, -1, 0)])  # not on the contract

	def test_a_submitted_change_order_is_not_cancelled(self):
		doc = self.change(self.station(), [(OTHER, 1, 12000)])
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()

	def test_the_scope_tab_lists_it_with_quantities_only_for_the_site(self):
		station = self.station()
		doc = self.change(station, [(OTHER, 1, 12000)])
		frappe.set_user(self.mostafa)
		orders = tab(station.name, "scope")["change_orders"]
		frappe.set_user("Administrator")
		self.assertEqual([o.name for o in orders], [doc.name])
		self.assertNotIn("delta_amount", orders[0])
		self.assertEqual(orders[0].lines[0].qty, 1)

	def test_only_who_may_change_the_contract_makes_a_change_order(self):
		manager = make_user("sp.co.pm@example.com", ("project_manager",))
		self.assertTrue(frappe.has_permission(co.CHANGE_ORDER, "create", user=self.amira))
		self.assertFalse(frappe.has_permission(co.CHANGE_ORDER, "create", user=manager))
		self.assertTrue(frappe.has_permission(co.CHANGE_ORDER, "read", user=manager))

	def test_the_form_offers_the_contract_lines_to_return_at_their_price(self):
		station = self.station()
		frappe.set_user(self.amira)
		lines = co.contract_lines(station.name)
		price = co.line_price(station.name, OTHER)
		frappe.set_user("Administrator")
		self.assertEqual(
			[(line["item_code"], line["left"], line["rate"], line["cost"]) for line in lines],
			[(PANEL, 40, 5000, 4000)],
		)
		self.assertEqual(set(price), {"rate", "cost"})
		frappe.set_user(self.mostafa)
		try:
			with self.assertRaises(frappe.PermissionError):
				co.contract_lines(station.name)  # the site does not change the contract
		finally:
			frappe.set_user("Administrator")
