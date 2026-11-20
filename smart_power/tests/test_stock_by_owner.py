"""I3 Stock by location and owner (SP-87): company stock and the supplier's consignment stay in
separate rows, and store keepers see quantities only."""

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests import IntegrationTestCase

from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock.report.sp_stock_by_owner.sp_stock_by_owner import columns, execute
from smart_power.sp_stock.stock_by_owner import SMART_POWER
from smart_power.tests.test_consignment import SUPPLIER, ensure_supplier
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"
ITEM = "_Test SP87 Panel"
ON_CONSIGNMENT, IN_STORE, RATE = 198, 20, 4000  # 6 pallets of 33 panels


class TestStockByOwner(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		ensure_supplier()
		cls.keeper = make_user("sp.i3.keeper@example.com", ("main_store_keeper",))
		cls.admin = make_user("sp.i3.admin@example.com", ("admin",))
		if not frappe.db.exists("Item", ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": ITEM,
					"item_name": "SP87 Panel 710 W",
					"item_group": frappe.db.get_value("Item Group", {"is_group": 0}),
					"stock_uom": "Nos",
					"is_stock_item": 1,
				}
			).insert()
		cls.main = frappe.db.get_value("Warehouse", {"company": COMPANY, "warehouse_name": "المخزن الرئيسي"})

	def setUp(self):
		frappe.db.delete("SP Consignment Container", {"item": ITEM})
		self.addCleanup(frappe.set_user, "Administrator")

	def stock(self):
		frappe.get_doc(
			{
				"doctype": "SP Consignment Container",
				"supplier": SUPPLIER,
				"item": ITEM,
				"company": COMPANY,
				"container_no": "SP87-1",
				"location": "Ard El-Salam",
				"pallets": 6,
				"per_pallet": 33,
			}
		).insert()
		# the class shares one transaction: what earlier tests put in the store is still there
		self.before = (
			frappe.db.get_value("Bin", {"item_code": ITEM, "warehouse": self.main}, "actual_qty") or 0
		)
		make_stock_entry(item_code=ITEM, qty=IN_STORE, to_warehouse=self.main, rate=RATE, company=COMPANY)

	def rows(self, user, **filters):
		frappe.set_user(user)
		try:
			return execute({"item_code": ITEM, **filters})
		finally:
			frappe.set_user("Administrator")

	def test_consignment_and_company_stock_are_two_rows_with_their_owner(self):
		self.stock()
		_cols, rows = self.rows(self.admin)
		by_owner = {r["owner_kind"]: r for r in rows}
		self.assertEqual(len(rows), 2)
		company, supplier = by_owner["company"], by_owner["supplier"]
		self.assertEqual(
			(company["owner"], company["location"], company["on_hand"]),
			(SMART_POWER, self.main, self.before + IN_STORE),
		)
		self.assertEqual(
			(supplier["location"], supplier["on_hand"], supplier["value"]),
			("Ard El-Salam", ON_CONSIGNMENT, None),
		)
		self.assertEqual(company["value"], (self.before + IN_STORE) * RATE)
		only_company = self.rows(self.admin, owner="company")[1]
		self.assertEqual([r["owner_kind"] for r in only_company], ["company"])

	def test_the_store_keeper_sees_no_value(self):
		self.stock()
		cols, rows = self.rows(self.keeper)
		self.assertNotIn("value", [c["fieldname"] for c in cols])
		self.assertTrue(all("value" not in r for r in rows))
		frappe.set_user(self.admin)
		try:
			self.assertIn("value", [c["fieldname"] for c in columns()])
		finally:
			frappe.set_user("Administrator")

	def test_reserved_stock_leaves_less_available(self):
		self.stock()
		frappe.db.set_value("Bin", {"item_code": ITEM, "warehouse": self.main}, "reserved_stock", 5)
		company = next(r for r in self.rows(self.admin)[1] if r["owner_kind"] == "company")
		self.assertEqual((company["reserved"], company["available"]), (5, self.before + IN_STORE - 5))


class TestShowroomStockLow(IntegrationTestCase):
	"""Showroom items at or under their reorder level: the report filter, the card and the alert."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		cls.keeper = make_user("sp.i3.showroom@example.com", ("showroom_store_keeper",))
		cls.showroom = frappe.db.get_value("Warehouse", {"company": COMPANY, "warehouse_type": "Showroom"})
		cls.items = {}
		for code, level in (("_Test SP87 MC4", 10), ("_Test SP87 Cable", 50)):
			if not frappe.db.exists("Item", code):
				frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": code,
						"item_name": code,
						"item_group": frappe.db.get_value("Item Group", {"is_group": 0}),
						"stock_uom": "Nos",
						"is_stock_item": 1,
					}
				).insert()
			item = frappe.get_doc("Item", code)
			item.set("reorder_levels", [])
			item.append(
				"reorder_levels",
				{
					"warehouse": cls.showroom,
					"warehouse_reorder_level": level,
					"warehouse_reorder_qty": level,
					"material_request_type": "Purchase",
				},
			)
			item.save()
			cls.items[code] = level

	def test_low_items_are_listed_alerted_and_counted_on_the_card(self):
		from smart_power.dashboards.cards import showroom_stock_low
		from smart_power.sp_stock.showroom_stock import check_showroom_stock, low_items

		make_stock_entry(
			item_code="_Test SP87 MC4", qty=4, to_warehouse=self.showroom, rate=10, company=COMPANY
		)
		make_stock_entry(
			item_code="_Test SP87 Cable", qty=500, to_warehouse=self.showroom, rate=10, company=COMPANY
		)
		low = {r["item_code"]: r for r in low_items(COMPANY)}
		self.assertIn("_Test SP87 MC4", low)
		self.assertNotIn("_Test SP87 Cable", low)
		self.assertEqual(low["_Test SP87 MC4"]["reorder_level"], 10)
		self.assertGreaterEqual(check_showroom_stock(), 1)
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": self.keeper, "sp_event": "showroom_stock_low"})
		)
		card = showroom_stock_low(self.keeper)
		self.assertGreaterEqual(card["value"], 1)
		self.assertEqual(
			(card["route"], card["route_options"]["below_reorder"]),
			(["query-report", "SP Stock by Owner"], 1),
		)
