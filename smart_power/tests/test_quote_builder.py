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

	def test_a_line_without_an_item_waits_for_a_pick(self):
		waiting = {
			r["line_key"]: r for r in builder.recalc(self.name, {"inputs": self.sample["inputs"]})["pending"]
		}
		self.assertIn("cable", waiting)
		self.assertTrue(waiting["cable"]["item_group"])
		picked = builder.recalc(self.name, self.data_for(100))
		self.assertNotIn("cable", {r["line_key"] for r in picked["pending"]})
		self.assertTrue(self.line(picked, "cable"))

	def test_each_line_says_how_its_price_may_change(self):
		page = builder.recalc(self.name, self.data_for(100))
		panels, motor = self.line(page, "panels"), self.line(page, "motor")
		self.assertEqual((panels["markup_editable"], panels["rate_editable"]), (True, False))
		self.assertEqual((motor["markup_editable"], motor["rate_editable"]), (False, False))

	def test_stock_beside_each_pick(self):
		page = builder.recalc(self.name, self.data_for(100))
		line = self.line(page, "panels")
		self.assertEqual(set(line["stock"]), {"company", "consignment"})
		frappe.set_user(self.camelia)
		try:
			self.assertFalse([r for r in self.page()["lines"] if "stock" in r])
		finally:
			frappe.set_user("Administrator")

	def test_a_print_group_survives_the_next_save(self):
		modified = self.page()["header"]["modified"]
		data = {**self.data_for(100), "merge": {"cable": "well set"}}
		builder.save(self.name, data, modified)
		page = self.page()
		self.assertEqual(self.line(page, "cable")["merge"], "well set")
		# the page sends back what it loaded
		merge = {r["line_key"]: r["merge"] for r in page["lines"] if r["line_key"]}
		builder.save(self.name, {**self.data_for(120), "merge": merge}, page["header"]["modified"])
		self.assertEqual(self.line(self.page(), "cable")["merge"], "well set")

	def test_the_pick_screen_lists_options_with_stock_and_price_date(self):
		pick = builder.pick_options(self.name, "motor", self.data_for(100))
		self.assertTrue(pick["sized"])
		self.assertEqual(pick["capacity"], "hp")
		self.assertTrue(pick["brands"])
		first = pick["options"][0]
		self.assertTrue(first["fits"])
		for field in ("company", "consignment", "price", "price_date", "brand"):
			self.assertIn(field, first)
		self.assertEqual(len([o for o in pick["options"] if o["current"]]), 1)
		self.assertFalse(frappe.db.exists("Quotation Item", {"parent": self.name, "sp_line_key": "cable"}))

	def test_a_chosen_brand_prices_the_line_and_goes_back(self):
		data = self.data_for(100)
		brand = frappe.db.get_value(
			"Item", self.line(builder.recalc(self.name, data), "motor")["item_code"], "brand"
		)
		chosen = {**data, "overrides": {**data["overrides"], "motor": {"brand": brand}}}
		self.assertEqual(
			frappe.db.get_value(
				"Item", self.line(builder.recalc(self.name, chosen), "motor")["item_code"], "brand"
			),
			brand,
		)

	def test_only_the_creator_opens_the_pick_screen(self):
		frappe.set_user(self.camelia)
		try:
			with self.assertRaises(frappe.PermissionError):
				builder.pick_options(self.name, "motor", self.data_for(100))
		finally:
			frappe.set_user("Administrator")

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
				# a type with no template yet (on-grid has one since SP-173): one hand line to start from
				"system_types": [{"system_type": "System Type-IRRIGATION"}],
			}
		).insert()
		name = builder.start(case.name)["quotation"]
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
