"""Item import from Excel with Arabic headers (SP-29)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.xlsxutils import make_xlsx

from smart_power.sp_stock.item_import import COLUMNS, import_items, import_rows
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

AR = {fieldname: ar for fieldname, ar, _en, _n in COLUMNS}
GROUP = "_Test Item Group"
UOM = "_Test UOM"


def upload(rows, name="items.xlsx"):
	content = make_xlsx(rows, "Items").getvalue()
	return frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 1}).insert(
		ignore_permissions=True
	)


class TestItemImport(IntegrationTestCase):
	def test_arabic_headers_create_items(self):
		header = [AR[f] for f in ("item_code", "sp_name_ar", "item_group", "stock_uom", "sp_watt")]
		rows = [header] + [[f"IMP-PNL-{i}", f"لوح تجربة {i}", GROUP, UOM, 600 + i] for i in range(300)]
		result = import_items(upload(rows).file_url)
		self.assertEqual((result["created"], result["errors"]), (300, 0))
		self.assertEqual(
			frappe.db.get_value("Item", "IMP-PNL-7", ["sp_name_ar", "sp_watt"]), ("لوح تجربة 7", 607)
		)

	def test_existing_code_updates_and_blank_keeps(self):
		header = [AR["item_code"], AR["sp_name_ar"], AR["item_group"], AR["stock_uom"], AR["sp_watt"]]
		import_rows([header, ["IMP-UPD-1", "قبل", GROUP, UOM, 500]])
		result = import_rows([header, ["IMP-UPD-1", "بعد", None, None, None]])
		self.assertEqual((result["updated"], result["created"]), (1, 0))
		self.assertEqual(frappe.db.get_value("Item", "IMP-UPD-1", ["sp_name_ar", "sp_watt"]), ("بعد", 500))

	def test_english_headers_work_too(self):
		result = import_rows(
			[["Item Code", "Arabic Name", "Item Group", "UOM"], ["IMP-EN-1", "صنف", GROUP, UOM]]
		)
		self.assertEqual(result["created"], 1)

	def test_bad_rows_are_reported_and_the_rest_saves(self):
		header = [
			AR[f] for f in ("item_code", "sp_name_ar", "item_group", "stock_uom", "brand", "sp_vmp", "sp_voc")
		]
		result = import_rows(
			[
				header,
				["IMP-OK-1", "سليم", GROUP, UOM, None, 40, 48],
				["IMP-DUP-1", "أول", GROUP, UOM, None, None, None],
				["IMP-DUP-1", "مكرر", GROUP, UOM, None, None, None],
				["IMP-BAD-GRP", "مجموعة خطأ", "مجموعة غير موجودة", UOM, None, None, None],
				["IMP-BAD-BRAND", "ماركة خطأ", GROUP, UOM, "PM TECH X", None, None],
				["IMP-BAD-SPEC", "مواصفات خطأ", GROUP, UOM, None, 50, 40],
				[None, "بدون كود", GROUP, UOM, None, None, None],
			]
		)
		by_code = {r["item_code"]: r for r in result["rows"]}
		self.assertEqual((result["created"], result["errors"]), (2, 5))
		dup = [r for r in result["rows"] if r["item_code"] == "IMP-DUP-1"]
		self.assertEqual([r["status"] for r in dup], ["Created", "Error"])
		self.assertEqual(dup[1]["row"], 4)
		for code in ("IMP-BAD-GRP", "IMP-BAD-BRAND", "IMP-BAD-SPEC"):
			self.assertEqual(by_code[code]["status"], "Error", code)
			self.assertFalse(frappe.db.exists("Item", code), code)
		self.assertTrue(frappe.db.exists("Item", "IMP-OK-1"))

	def test_only_item_creators_can_import(self):
		gaber = make_user("sp.import.gaber@example.com", ("main_store_keeper",))
		file_url = upload([[AR["item_code"]], ["IMP-NO-1"]]).file_url
		frappe.set_user(gaber)
		try:
			with self.assertRaises(frappe.PermissionError):
				import_items(file_url)
		finally:
			frappe.set_user("Administrator")
