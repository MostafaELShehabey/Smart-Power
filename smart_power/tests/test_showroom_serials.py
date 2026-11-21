"""SH1 showroom sale with serials (SP-179): a pump is sold with its serial and nameplate photo, its
warranty starts on the sale date, and a return names the serial that comes back."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, getdate, today

from smart_power.sp_finance import centers
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_sales import showroom_sale as ss
from smart_power.sp_stock import prices
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock import warranty as wr
from smart_power.tests.test_prices import make_item
from smart_power.tests.test_transfers import photo
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule, set_setting

load_erpnext_test_data()

COMPANY, PRICE, COST = "_Test Company", 20000, 15000
WARRANTY_YEARS, BRAND_YEARS = 2, 1


class SerialCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		made = centers.seed_centers(COMPANY)
		set_setting(**{f"center_{k}": v for k, v in made.items()})
		cls.cashier = make_user("sp.shs.cashier@example.com", ("showroom_cashier",))
		tag = frappe.generate_hash(length=6)
		cls.pump = make_item(f"SP179-PUMP-{tag}", is_stock_item=1, has_serial_no=1).name
		frappe.db.set_value("Item", cls.pump, "sp_warranty_years", WARRANTY_YEARS)
		prices.set_price(cls.pump, prices.BTC, PRICE)
		cls.store = wh.warehouse_of(COMPANY, wh.SHOWROOM)
		cls.serials = [f"SP179-P-{tag}-1", f"SP179-P-{tag}-2"]
		frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": COMPANY,
				"items": [
					{
						"item_code": cls.pump,
						"qty": 2,
						"t_warehouse": cls.store,
						"basic_rate": COST,
						"use_serial_batch_fields": 1,
						"serial_no": "\n".join(cls.serials),
					}
				],
			}
		).insert().submit()
		ss.seed_pos_profile(COMPANY)

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		set_setting(showroom_discount_max_pct=0)
		set_rule("showroom_discount_max", "Warn")
		frappe.defaults.set_user_default("company", COMPANY, self.cashier)

	def as_cashier(self, action, *args, **kwargs):
		frappe.set_user(self.cashier)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def sell(self, units):
		return self.as_cashier(
			ss.sell, {"items": [{"item_code": self.pump, "qty": len(units) or 1, "serials": units}]}
		)

	def nameplate(self):
		frappe.set_user(self.cashier)
		try:
			return photo(self)
		finally:
			frappe.set_user("Administrator")


class TestNoSerial(SerialCase):
	def test_a_pump_sold_without_a_serial_or_photo_cannot_be_saved(self):
		before = frappe.db.count(ss.SI, {"naming_series": ss.SERIES})
		self.assertRaises(frappe.ValidationError, self.sell, [])
		self.assertRaises(frappe.MandatoryError, self.sell, [{"serial_no": self.serials[0]}])
		outside = [{"serial_no": "NOT-IN-THE-STORE", "photo": self.nameplate()}]
		self.assertRaises(frappe.ValidationError, self.sell, outside)
		self.assertEqual(frappe.db.count(ss.SI, {"naming_series": ss.SERIES}), before)
		self.assertEqual(self.as_cashier(ss.store_serials, self.pump), sorted(self.serials))


class TestSoldAndReturned(SerialCase):
	def test_the_serial_leaves_with_its_photo_its_warranty_starts_today_and_a_return_voids_it(self):
		url = self.nameplate()
		sale = self.sell([{"serial_no": self.serials[0], "photo": url}])
		self.assertEqual(frappe.db.get_value("Serial No", self.serials[0], "warehouse"), None)
		row = frappe.get_doc(wr.WARRANTY, {"serial_no": self.serials[0], "sales_invoice": sale["name"]})
		self.assertEqual(
			(row.source, row.start_basis, str(row.start_date), row.months, row.nameplate_photo),
			(wr.SHOWROOM, wr.SALE_DATE, today(), WARRANTY_YEARS * 12, url),
		)
		self.assertEqual(getdate(row.end_date), add_months(getdate(today()), WARRANTY_YEARS * 12))
		taken = frappe.get_all("SP Serial Photo", {"reference_name": sale["name"]}, ["serial_no", "point"])
		self.assertEqual([(t.serial_no, t.point) for t in taken], [(self.serials[0], "Showroom sale")])
		self.assertIn(self.serials[0], self.as_cashier(ss.receipt, sale["name"]))  # printed

		found = self.as_cashier(ss.find_receipt, sale["name"])
		self.assertEqual(found["items"][0]["serials"], [self.serials[0]])
		wrong = [{"item_code": self.pump, "qty": 1, "serials": [self.serials[1]]}]
		self.assertRaises(frappe.ValidationError, self.as_cashier, ss.return_sale, sale["name"], wrong)
		back = [{"item_code": self.pump, "qty": 1, "serials": [self.serials[0]]}]
		self.as_cashier(ss.return_sale, sale["name"], back)
		self.assertEqual(frappe.db.get_value("Serial No", self.serials[0], "warehouse"), self.store)
		self.assertEqual(frappe.db.get_value(wr.WARRANTY, row.name, "status"), wr.VOID)


class TestBrandYears(SerialCase):
	def test_without_item_years_the_brand_years_count(self):
		brand = frappe.get_doc({"doctype": "Brand", "brand": f"SP179 Brand {frappe.generate_hash(length=4)}"})
		brand.sp_warranty_years = BRAND_YEARS
		brand.insert()
		frappe.db.set_value("Item", self.pump, {"sp_warranty_years": 0, "brand": brand.name})
		self.assertEqual(ss.warranty_months(self.pump), BRAND_YEARS * 12)
