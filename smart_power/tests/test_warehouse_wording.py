"""The stores screen reads as the rest of the system does (BUG-35)."""

import frappe
from frappe.desk.form.meta import get_meta
from frappe.tests import IntegrationTestCase

ARABIC = {
	"Inventory": "المخزون",
	"Warehouse": "المخزن",
	"Warehouses": "المخازن",
	"Warehouse Tree": "شجرة المخازن",
	"Expand/Collapse": "توسيع / طي",
	"Show all (including disabled)": "عرض الكل (مع المعطّل)",
	"Reload Tree": "إعادة تحميل الشجرة",
}


class TestWarehouseWording(IntegrationTestCase):
	def test_the_stores_screen_is_arabic(self):
		for source, arabic in ARABIC.items():
			with self.subTest(source=source):
				self.assertEqual(frappe._(source, lang="ar"), arabic)

	def test_a_tree_title_reads_in_arabic_order(self):
		self.assertEqual(frappe._("{0} Tree", lang="ar").format("الحسابات"), "شجرة الحسابات")

	def test_the_stores_tree_has_its_own_title(self):
		tree_js = get_meta("Warehouse").as_dict().get("__tree_js") or ""
		self.assertIn('settings.title = __("Warehouse Tree")', tree_js)
