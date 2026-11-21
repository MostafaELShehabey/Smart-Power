"""Serial numbers, phase 1 (SP-179): a group's flag tracks its items by serial; commissioning a
motor needs its serial and nameplate photo, and it joins the warranty register."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.setup.seed import seed_list_values
from smart_power.sp_site import commissioning as com
from smart_power.sp_stock import serials as sr
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock import warranty as wr
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_transfers import photo
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()

COMPANY, PUMP = "_Test Company", "System Type-PUMP"
MOTORS, SUB = "_SP179 Motors", "_SP179 Motors 10HP"
SERIAL = "SP179-MOTOR-0001"
ONE_YEAR = 12  # sp-allow-number: months of the story's 1-year cover


def group(name, parent="All Item Groups", tracked=0, is_group=0):
	if not frappe.db.exists("Item Group", name):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": name,
				"parent_item_group": parent,
				"is_group": is_group,
			}
		).insert()
	doc = frappe.get_doc("Item Group", name)
	doc.sp_serial_tracked = tracked
	doc.save()
	return doc


class TestGroupFlag(IntegrationTestCase):
	def test_a_new_item_of_a_tracked_group_or_its_sub_group_is_serial_tracked(self):
		group(MOTORS, tracked=1, is_group=1)
		group(SUB, parent=MOTORS)
		self.assertTrue(sr.tracked_group(SUB))
		item = make_item("SP179-NEW", item_group=SUB, is_stock_item=1)
		self.assertEqual(item.has_serial_no, 1)

	def test_turning_the_flag_on_skips_items_that_already_moved_stock(self):
		group(MOTORS, tracked=0, is_group=1)
		moved = make_item("SP179-MOVED", item_group=MOTORS, is_stock_item=1)
		fresh = make_item("SP179-FRESH", item_group=MOTORS, is_stock_item=1)
		frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"company": COMPANY,
				"items": [
					{
						"item_code": moved.name,
						"qty": 1,
						"t_warehouse": "Stores - _TC",
						"basic_rate": 100,
					}
				],
			}
		).insert().submit()
		group(MOTORS, tracked=1, is_group=1)
		self.assertEqual(frappe.db.get_value("Item", fresh.name, "has_serial_no"), 1)
		self.assertEqual(frappe.db.get_value("Item", moved.name, "has_serial_no"), 0)


class TestCommissioningRegister(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_list_values()
		com.seed_commissioning_templates()
		cls.motor = make_item(
			"SP179-MOTOR", item_group="_Test Item Group", has_serial_no=1, is_stock_item=1
		).name

	def commissioning(self, nameplate=None, operation_date="2027-01-10"):
		station = frappe.get_doc(
			{
				"doctype": "SP Station",
				"customer": "_Test Customer",
				"company": COMPANY,
				"systems": [{"system_type": PUMP, "capacity_kw": 10, "qty": 1}],
			}
		).insert()
		doc = frappe.get_doc(
			{
				"doctype": "SP Commissioning",
				"station": station.name,
				"system_row": station.systems[0].name,
				"operation_date": operation_date,
				"components": [
					{
						"component_type": "Motor",
						"item": self.motor,
						"serial": SERIAL,
						"warranty_months": ONE_YEAR,
						"nameplate_photo": nameplate,
					}
				],
			}
		).insert()
		for row in doc.checklist:
			row.done = 1
		doc.save()
		return doc

	def test_a_motor_without_its_nameplate_photo_is_refused(self):
		doc = self.commissioning()
		self.assertRaises(frappe.MandatoryError, doc.submit)

	def test_a_motor_commissioned_10_1_2027_with_1_year_ends_10_1_2028(self):
		doc = self.commissioning(photo(self))
		doc.submit()
		row = frappe.get_doc(wr.WARRANTY, {"serial_no": SERIAL, "commissioning": doc.name})
		self.assertEqual(
			(str(row.start_date), str(row.end_date), row.months, row.customer, row.source, row.start_basis),
			("2027-01-10", "2028-01-10", ONE_YEAR, "_Test Customer", wr.STATION, wr.OPERATION_DATE),
		)
		self.assertEqual(str(doc.components[0].warranty_end), "2028-01-10")
		events = [r["reference_name"] for r in sr.history(SERIAL)]
		self.assertIn(doc.name, events)  # the lookup by serial
		self.assertIn(row.name, events)
		doc.cancel()
		self.assertEqual(frappe.db.get_value(wr.WARRANTY, row.name, "status"), wr.VOID)
