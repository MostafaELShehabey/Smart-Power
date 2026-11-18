"""Q2 Quote Builder (SP-57): a pump request opens priced; a changed depth reprices; a typed
quantity stays and is tagged; the margin chip; costs only for the quote's creator."""

import time

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_quotes import builder
from smart_power.sp_quotes.calc_templates import seed_calc_templates
from smart_power.sp_stock import prices
from smart_power.sp_stock.item import seed_item_groups
from smart_power.sp_stock.prices import BTC, COST
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_pump_template import golden, prefer, set_up_items
from smart_power.tests.utils import load_erpnext_test_data, make_customer, make_user, set_setting

load_erpnext_test_data()

PUMP = "System Type-PUMP"
REQUEST = {"hp": 20, "well_depth_m": 120, "water_level_m": 40, "pump_depth_m": 100}


class TestQuoteBuilder(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_item_groups()
		seed_calc_templates()
		cls.data = golden()
		set_up_items(cls.data)
		cls.sample = next(iter(cls.data["cases"].values()))
		shipped = frappe.get_all(
			"SP Calc Template Line", {"parenttype": "SP Calc Template"}, pluck="item_group"
		)
		prefer(cls.sample, {g for g in shipped if g})
		cls.aya = make_user("sp.qb.aya@example.com", ("quote_creator",))
		cls.camelia = make_user("sp.qb.camelia@example.com", ("followup_all",))
		cls.owner = make_user("sp.qb.owner@example.com", ("lead_intake", "customer_followup"))
		cls.customer = make_customer("01009990571", "عميل المنشئ")

	def setUp(self):
		set_setting(margin_ranges=[{"scope": "Supply and install", "min_pct": 9, "max_pct": 11}])
		self.case = frappe.get_doc(
			{
				"doctype": "SP Case",
				"customer": self.customer,
				"channel": "Call",
				"follow_up_owner": self.owner,
				"quote_creator": self.aya,
				"system_types": [{"system_type": PUMP}],
				"request_details": REQUEST,
			}
		).insert()
		self.name = builder.start(self.case.name)["quotation"]

	def page(self):
		return builder.load(self.name)

	def line(self, page, key):
		return next((r for r in page["lines"] if r["line_key"] == key), None)

	def test_a_pump_request_opens_filled_and_priced(self):
		page = self.page()
		self.assertEqual(page["header"]["customer"], self.customer)
		values = {i["input_key"]: i["value"] for i in page["inputs"]}
		self.assertEqual((flt(values["hp"]), flt(values["pump_depth"])), (20, 100))
		self.assertTrue([r for r in page["lines"] if r["line_key"]])
		self.assertEqual(builder.start(self.case.name)["quotation"], self.name)  # one open draft

	def data_for(self, depth=100, **typed):
		"""The golden case's inputs and item choices, at a pump depth, with typed quantities."""
		overrides = {
			k: {f: v for f, v in row.items() if f != "qty"} for k, row in self.sample["overrides"].items()
		}
		for key, qty in typed.items():
			overrides.setdefault(key, {})["qty"] = qty
		return {"inputs": {**self.sample["inputs"], "pump_depth": depth}, "overrides": overrides}

	def test_a_deeper_pump_reprices_without_saving(self):
		before = builder.recalc(self.name, self.data_for(100))
		started = time.monotonic()
		deeper = builder.recalc(self.name, self.data_for(120))
		self.assertLess(time.monotonic() - started, 3)  # under 1 s in use; CI runners are slower
		for key in ("column_pipes", "cable", "rope"):
			self.assertGreater(self.line(deeper, key)["qty"], self.line(before, key)["qty"], key)
		self.assertGreater(deeper["summary"]["sell"], before["summary"]["sell"])
		self.assertFalse(frappe.db.exists("Quotation Item", {"parent": self.name, "sp_line_key": "cable"}))

	def test_a_typed_quantity_stays_and_is_tagged(self):
		modified = self.page()["header"]["modified"]
		self.assertEqual(
			self.line(builder.recalc(self.name, self.data_for(100, column_pipes=38)), "column_pipes")["qty"],
			38,
		)
		again = self.line(builder.recalc(self.name, self.data_for(120, column_pipes=38)), "column_pipes")
		self.assertEqual((again["qty"], again["manual"]), (38, 1))
		builder.save(self.name, self.data_for(120, column_pipes=38), modified)
		saved = self.line(self.page(), "column_pipes")
		self.assertEqual((saved["qty"], saved["manual"]), (38, 1))

	def test_a_margin_out_of_range_is_shown_and_never_stops(self):
		code = "SP57-HAND"
		make_item(code)
		prices.set_price(code, COST, 930, price_date=today())
		prices.set_price(code, BTC, 1000, price_date=today())
		case = frappe.get_doc(
			{
				"doctype": "SP Case",
				"customer": self.customer,
				"channel": "Call",
				"follow_up_owner": self.owner,
				"quote_creator": self.aya,
				"system_types": [{"system_type": "System Type-ONGRID"}],
				"request_details": {"kw": 15},
			}
		).insert()
		name = builder.start(case.name)["quotation"]  # no template yet: one hand line to start from
		hand = [{"item_code": code, "qty": 1, "rate": 1000, "sp_cost": 930}]
		page = builder.save(name, {"hand_lines": hand}, builder.load(name)["header"]["modified"])
		self.assertEqual(round(page["summary"]["margin"], 1), 7)
		self.assertFalse(page["summary"]["range"]["in_range"])

	def test_someone_elses_save_is_not_overwritten(self):
		with self.assertRaises(frappe.TimestampMismatchError):
			builder.save(self.name, self.data_for(100), "2020-01-01 00:00:00")

	def test_follow_up_reads_it_at_sale_prices(self):
		frappe.set_user(self.camelia)
		try:
			page = self.page()
			self.assertIsNone(page["summary"])
			self.assertFalse(page["can_edit"])
			self.assertTrue(all("cost" not in r and "profit" not in r for r in page["lines"]))
			with self.assertRaises(frappe.PermissionError):
				builder.recalc(self.name, {})
		finally:
			frappe.set_user("Administrator")

	def test_the_creator_works_on_her_quote(self):
		frappe.set_user(self.aya)
		try:
			page = self.page()
			self.assertTrue(page["can_edit"])
			self.assertIsNotNone(page["summary"])
		finally:
			frappe.set_user("Administrator")
