"""Price import from Excel (SP-30): upsert by item code, dates, suppliers, reasons and cost access."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today
from frappe.utils.xlsxutils import make_xlsx

from smart_power.sp_stock import prices
from smart_power.sp_stock.price_import import COLUMNS, import_prices, import_rows
from smart_power.sp_stock.prices import BTB, BTC, COST, LIST
from smart_power.tests.test_prices import SHEET_RULES, make_category, make_item
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

AR = {fieldname: ar for fieldname, ar, _en in COLUMNS}
SUPPLIER = "_Test Supplier"


def header(*fields):
	return [AR[f] for f in fields]


def upload(rows, name="prices.xlsx"):
	content = make_xlsx(rows, "Prices").getvalue()
	return frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 1}).insert(
		ignore_permissions=True
	)


class TestPriceImport(IntegrationTestCase):
	def setUp(self):
		suffix = frappe.generate_hash(length=6)
		self.items = [make_item(f"SP-PIMP-{suffix}-{i}").name for i in range(3)]

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_arabic_headers_with_dates_and_suppliers(self):
		rows = [header("item_code", "supplier", "price_date", COST, BTB, BTC)] + [
			[code, SUPPLIER, "05-11-2026", 870 + i, 1200 + i, 1270 + i] for i, code in enumerate(self.items)
		]
		result = import_prices(upload(rows).file_url)
		self.assertEqual((result["saved"], result["errors"]), (3, 0))
		cost = prices.latest_price(self.items[0], COST, on_date="2026-11-30")
		# 05-11-2026 is the 5th of November (day first, like the sheets)
		self.assertEqual((cost.rate, cost.supplier, cost.date), (870, SUPPLIER, getdate("2026-11-05")))
		self.assertEqual(prices.latest_price(self.items[2], BTC, on_date="2026-11-30").rate, 1272)

	def test_upsert_logs_the_file_as_the_reason_and_blank_keeps_the_price(self):
		code = self.items[0]
		import_rows([header("item_code", BTB, BTC), [code, 5200, 5600]])
		result = import_rows([header("item_code", BTB, BTC), [code, 5450, ""]], source="list 28-10.xlsx")
		self.assertEqual(result["rows"][0]["status"], "Saved")
		self.assertEqual(
			(prices.latest_price(code, BTB).rate, prices.latest_price(code, BTC).rate), (5450, 5600)
		)
		reason = frappe.get_all(
			"SP Edit Reason Log",
			{"reference_doctype": "Item Price", "new_value": ("like", "5450%")},
			pluck="reason",
		)
		self.assertIn(frappe._("Import: {0}").format("list 28-10.xlsx"), reason)

	def test_same_price_again_is_unchanged_but_a_stale_date_is_fixed(self):
		code = self.items[0]
		old = add_days(today(), -400)
		prices.set_price(code, BTC, 1000, price_date=old)
		result = import_rows([header("item_code", BTC), [code, 1000]])
		self.assertEqual(result["rows"][0]["status"], "Saved")
		self.assertEqual(prices.latest_price(code, BTC).date, getdate(today()))
		result = import_rows([header("item_code", BTC), [code, 1000]])
		self.assertEqual(result["rows"][0]["status"], "Unchanged")

	def test_bad_rows_do_not_stop_the_good_ones(self):
		rows = [
			header("item_code", "supplier", BTC, COST),
			[self.items[0], SUPPLIER, 1000, 800],
			["NO-SUCH-ITEM", SUPPLIER, 1000, 800],
			[self.items[1], "No Such Supplier", 1000, 800],
			[self.items[0], SUPPLIER, 1100, 900],
			[self.items[2], SUPPLIER, -5, 800],
		]
		result = import_rows(rows)
		statuses = [(r["row"], r["status"]) for r in result["rows"]]
		self.assertEqual(statuses, [(2, "Saved"), (3, "Error"), (4, "Error"), (5, "Error"), (6, "Error")])
		self.assertIn("repeated", result["rows"][3]["message"])
		self.assertFalse(frappe.db.exists("Item Price", {"item_code": self.items[2]}))

	def test_list_price_runs_the_category_rules(self):
		category = make_category("_SP import rules", rules=SHEET_RULES).name
		code = make_item(
			"SP-PIMP-RULES-" + frappe.generate_hash(length=6), sp_price_age_category=category
		).name
		import_rows([header("item_code", LIST), [code, 1000]])
		self.assertEqual(prices.latest_price(code, BTC).rate, 1270)
		code2 = make_item(
			"SP-PIMP-NORULES-" + frappe.generate_hash(length=6), sp_price_age_category=category
		).name
		import_rows([header("item_code", LIST), [code2, 1000]], apply_rules=0)
		self.assertIsNone(prices.latest_price(code2, BTC))

	def test_cost_columns_need_cost_access(self):
		helper = make_user(
			"sp.pimp.helper@example.com", ("showroom_sales",), extra_roles=("Sales Master Manager",)
		)
		frappe.set_user(helper)
		with self.assertRaises(frappe.PermissionError):
			import_rows([header("item_code", COST), [self.items[0], 800]])
		result = import_rows([header("item_code", BTC), [self.items[0], 1000]])
		self.assertEqual(result["saved"], 1)

	def test_sales_cannot_import(self):
		camelia = make_user("sp.pimp.camelia@example.com", ("lead_intake", "customer_followup"))
		frappe.set_user(camelia)
		with self.assertRaises(frappe.PermissionError):
			import_prices(upload([header("item_code", BTC), [self.items[0], 1]]).file_url)

	def test_file_needs_a_code_and_a_price_column(self):
		with self.assertRaises(frappe.ValidationError):
			import_rows([header(BTC), [1000]])
		with self.assertRaises(frappe.ValidationError):
			import_rows([header("item_code", "supplier"), [self.items[0], SUPPLIER]])
