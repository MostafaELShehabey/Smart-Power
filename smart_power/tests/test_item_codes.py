"""Item coding scheme, per-group template and cleansing (SP-165)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.xlsxutils import make_xlsx

from smart_power.sp_stock import item_codes, prices
from smart_power.sp_stock.prices import BTC, COST
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()

GROUP, PUMPS = "_Test SP Panels", "_Test SP Pumps"
SUPPLIER = "_Test SP PM Tech"


def ensure(doctype, name, **values):
	if not frappe.db.exists(doctype, name):
		frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)
	else:
		frappe.db.set_value(doctype, name, {k: v for k, v in values.items() if k.startswith("sp_")})


def header(item_group, *fields):
	labels = {f: ar for f, ar, _en in item_codes.template_columns(item_group)}
	return [labels[f] for f in fields]


class TestItemCodes(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		root = (
			frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ("in", ("", None))})
			or "All Item Groups"
		)
		ensure(
			"Item Group",
			GROUP,
			item_group_name=GROUP,
			parent_item_group=root,
			sp_code_prefix="PNL",
			sp_required_specs="sp_watt, sp_voc",
		)
		ensure(
			"Item Group",
			PUMPS,
			item_group_name=PUMPS,
			parent_item_group=root,
			sp_code_prefix="PMP",
			sp_required_specs="sp_hp",
		)
		ensure("Brand", "_Test SP JA", brand="_Test SP JA", sp_code="TJA")
		ensure(
			"Brand",
			"_Test SP Ferat",
			brand="_Test SP Ferat",
			sp_code="TFERAT",
			sp_aliases="فيرات, FERAT pumps",
		)
		ensure(
			"Supplier",
			SUPPLIER,
			supplier_name=SUPPLIER,
			supplier_group=frappe.db.get_value("Supplier Group", {"is_group": 0}),
			sp_aliases="PM TECH, بي ام تك",
		)

	def test_the_code_is_group_brand_model(self):
		self.assertEqual(item_codes.make_code(GROUP, "_Test SP JA", "625"), "PNL-TJA-625")
		self.assertEqual(item_codes.make_code(PUMPS, "_Test SP Ferat", " sp110 - 09 "), "PMP-TFERAT-SP110-09")
		self.assertIsNone(item_codes.make_code(GROUP, "_Test SP JA", ""))

	def test_the_template_has_the_groups_specs_and_the_price_columns(self):
		fields = [f for f, _ar, _en in item_codes.template_columns(GROUP)]
		self.assertTrue(
			{
				"item_code",
				"sp_model",
				"brand",
				"stock_uom",
				"sp_watt",
				"sp_voc",
				"supplier",
				"price_date",
				BTC,
			}
			<= set(fields)
		)
		self.assertNotIn("sp_hp", fields)

	def test_the_filled_template_imports_coded_items_with_dated_supplier_prices(self):
		rows = [
			header(
				GROUP,
				"sp_model",
				"sp_name_ar",
				"brand",
				"stock_uom",
				"sp_watt",
				"sp_voc",
				"supplier",
				"price_date",
				COST,
				BTC,
			),
			["625", "لوح جا 625", "_Test SP JA", "Nos", 625, 49.5, "PM TECH", "28-10-2026", 4100, 4900],
			["630", "لوح جا 630", "_test sp ja", "Nos", 630, 49.8, "بي  ام تك", "28-10-2026", 4150, 4950],
			["640", "بدون مواصفات", "_Test SP JA", "Nos", "", "", "PM TECH", "28-10-2026", 4200, 5000],
			["645", "سعر بلا تاريخ", "_Test SP JA", "Nos", 645, 50, "PM TECH", "", 4250, 5050],
		]
		result = item_codes.import_checked(rows, GROUP, dry_run=0)
		by_row = {r["row"]: r for r in result["rows"]}
		self.assertEqual((by_row[2]["item_code"], by_row[2]["status"]), ("PNL-TJA-625", "OK"))
		self.assertEqual(by_row[3]["item_code"], "PNL-TJA-630")  # the brand's spelling is matched
		self.assertEqual(by_row[4]["status"], "Error")  # the group's specs are missing
		self.assertEqual(by_row[5]["status"], "Error")  # a price without its date
		self.assertEqual(result["imported"], 2)
		for code in ("PNL-TJA-625", "PNL-TJA-630"):
			item = frappe.get_doc("Item", code)
			self.assertEqual((item.item_group, item.stock_uom, item.brand), (GROUP, "Nos", "_Test SP JA"))
			self.assertTrue(item.sp_watt and item.sp_voc)
			cost = prices.latest_price(code, COST, on_date="2026-11-30")
			self.assertEqual(
				(cost.supplier, str(cost.date)), (SUPPLIER, "2026-10-28")
			)  # PM TECH / بي ام تك → one supplier
		self.assertFalse(frappe.db.exists("Item", "PNL-TJA-640"))

	def test_two_spellings_of_one_item_are_reported_and_only_one_is_created(self):
		rows = [
			header(PUMPS, "sp_model", "sp_name_ar", "brand", "stock_uom", "sp_hp"),
			["SP110-09", "طلمبة فيرات", "_Test SP Ferat", "Nos", 10],
			["sp110 - 09", "طلمبه فيرات", "فيرات", "Nos", 10],
		]
		checked = item_codes.import_checked(rows, PUMPS, dry_run=1)
		self.assertEqual([r["status"] for r in checked["rows"]], ["OK", "Duplicate"])
		self.assertIn("2", checked["rows"][1]["messages"][0])
		self.assertFalse(frappe.db.exists("Item", "PMP-TFERAT-SP110-09"))  # a dry run saves nothing
		done = item_codes.import_checked(rows, PUMPS, dry_run=0)
		self.assertEqual((done["imported"], done["duplicates"]), (1, 1))
		self.assertEqual(frappe.db.count("Item", {"item_code": ("like", "PMP-TFERAT-SP110%")}), 1)

	def test_from_an_uploaded_file(self):
		rows = [
			header(PUMPS, "sp_model", "brand", "stock_uom", "sp_hp"),
			["SP200", "_Test SP Ferat", "Nos", 20],
		]
		content = make_xlsx(rows, "Pumps").getvalue()
		f = frappe.get_doc(
			{"doctype": "File", "file_name": "pumps.xlsx", "content": content, "is_private": 1}
		).insert(ignore_permissions=True)
		self.assertEqual(item_codes.import_group(f.file_url, PUMPS, 0)["imported"], 1)
		self.assertTrue(frappe.db.exists("Item", "PMP-TFERAT-SP200"))
