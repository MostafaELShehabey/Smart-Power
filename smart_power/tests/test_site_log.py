"""Site daily log (SP-96): labour and materials cost the station; one log per site per day."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_site import site_log
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_workers import worker
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY, PIPE = "_Test Company", "_Test Item"


def account(name):
	return frappe.db.get_value("Account", {"company": COMPANY, "account_name": name, "is_group": 0})


class TestSiteLog(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from smart_power.sp_finance.accounts import seed_accounts

		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		# Smart Power keeps perpetual inventory, so a Material Issue posts its cost; the test company
		# does not, until this class (rolled back with it) turns it on
		frappe.db.set_value(
			"Company",
			COMPANY,
			{
				"enable_perpetual_inventory": 1,
				"default_inventory_account": "Stock In Hand - _TC",
				"stock_adjustment_account": "Stock Adjustment - _TC",
			},
		)
		frappe.clear_cache(doctype="Company")
		# ERPNext keeps the flag per company for the whole run (frappe.local)
		frappe.local.enable_perpetual_inventory = {
			**getattr(frappe.local, "enable_perpetual_inventory", {}),
			COMPANY: 1,
		}

	@classmethod
	def tearDownClass(cls):
		getattr(frappe.local, "enable_perpetual_inventory", {}).pop(COMPANY, None)
		super().tearDownClass()
		frappe.clear_cache(doctype="Company")

	def setUp(self):
		center = frappe.get_cached_value("Company", COMPANY, "cost_center")
		set_setting(
			account_map=[
				{
					"event": "Site Labour",
					"debit_account": account("Project Labour"),
					"debit_center_rule": "From document",
					"debit_cost_center": center,
					"credit_account": account("Daily Wages Payable"),
					"credit_center_rule": "Fixed",
					"credit_cost_center": center,
					"project_rule": "Debit side",
				}
			]
		)
		self.station = frappe.get_doc(
			{"doctype": "SP Station", "customer": "_Test Customer", "company": COMPANY}
		).insert()
		self.site = self.station.site_warehouse
		receipt = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": COMPANY,
				"items": [{"item_code": PIPE, "qty": 20, "t_warehouse": self.site, "basic_rate": 100}],
			}
		).insert()
		receipt.submit()
		self.crew = [worker(f"عامل يومية {n}", 350).name for n in range(3)]

	def log(self, materials=12, work_date=None, **kw):
		return frappe.get_doc(
			{
				"doctype": "SP Site Daily Log",
				"station": self.station.name,
				"work_date": work_date or today(),
				"crew": [{"employee": e, "days": 1} for e in self.crew],
				"materials": [{"item_code": PIPE, "qty": materials}] if materials else [],
				"stages": [{"stage": "Site Stage-PANELS"}],
				**kw,
			}
		).insert()

	def site_qty(self):
		return flt(frappe.db.get_value("Bin", {"item_code": PIPE, "warehouse": self.site}, "actual_qty"))

	def test_labour_and_materials_cost_the_station(self):
		log = self.log()
		self.assertEqual(log.labour_total, 1050)  # 3 workers x 1 day x 350
		self.assertEqual([r.wage for r in log.crew], [350, 350, 350])  # from the workers
		log.submit()
		self.assertEqual(self.site_qty(), 8)  # 20 - 12
		cost = site_log.station_cost(self.station.name)
		self.assertEqual(cost[account("Project Labour")], 1050)
		self.assertEqual(cost[account("Project Materials")], 1200)  # 12 x 100 valuation
		self.assertEqual(cost["total"], 2250)
		# the wages are owed until paid
		payable = frappe.db.get_value(
			"GL Entry", {"voucher_no": log.journal_entry, "account": account("Daily Wages Payable")}, "credit"
		)
		self.assertEqual(flt(payable), 1050)

	def test_one_log_per_site_per_day(self):
		self.log()
		with self.assertRaises(frappe.DuplicateEntryError):
			self.log(materials=0)
		self.log(materials=0, work_date=add_days(today(), -1))  # another day is fine

	def test_more_than_the_site_holds_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.log(materials=21)

	def test_wages_paid_from_custody(self):
		mostafa = make_user("sp.sl.mostafa@example.com", ("installation_manager", "custody_holder"))
		from smart_power.sp_finance.accounts import CUSTODY, holder_account

		custody = holder_account(mostafa, CUSTODY, COMPANY)
		log = self.log(materials=0, paid_from=custody)
		log.submit()
		credit = frappe.db.get_value(
			"GL Entry", {"voucher_no": log.journal_entry, "account": custody}, "credit"
		)
		self.assertEqual(flt(credit), 1050)

	def test_cancel_reverses_both_within_the_lock(self):
		log = self.log()
		log.submit()
		log.cancel()
		self.assertEqual(self.site_qty(), 20)
		self.assertEqual(site_log.station_cost(self.station.name)["total"], 0)
		old = self.log(materials=0, work_date=add_days(today(), -10))
		old.submit()
		manager = make_user("sp.sl.manager@example.com", ("installation_manager",))
		frappe.set_user(manager)
		try:
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc("SP Site Daily Log", old.name).cancel()  # past the 3-day lock
		finally:
			frappe.set_user("Administrator")

	def photo(self, doctype, name, file_name="panels-row.png"):
		import io

		from PIL import Image

		if file_name.endswith(".png"):
			png = io.BytesIO()
			Image.new("RGB", (4, 4), "gold").save(png, format="PNG")
			content = png.getvalue()
		else:
			content = b"receipt"
		return frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"content": content,
				"attached_to_doctype": doctype,
				"attached_to_name": name,
				"is_private": 1,
			}
		).insert()

	def test_photos_tagged_for_marketing(self):
		log = self.log(materials=0)
		photo = self.photo("SP Site Daily Log", log.name)
		receipt = self.photo("SP Site Daily Log", log.name, "receipt.txt")
		self.assertEqual([f.name for f in site_log.photos("SP Site Daily Log", log.name)], [photo.name])
		site_log.set_marketing(photo.name, 1)
		self.assertEqual(frappe.db.get_value("File", photo.name, "sp_usable_for_marketing"), 1)
		self.assertFalse(frappe.db.get_value("File", receipt.name, "sp_usable_for_marketing"))

	def test_station_photos_tagged_by_who_edits_the_station(self):
		"""SP-53: a finished station's own photos are tagged on the station; installations only
		read the station, so the project manager (or the admin) tags them."""
		photo = self.photo("SP Station", self.station.name)
		self.assertEqual([f.name for f in site_log.photos("SP Station", self.station.name)], [photo.name])
		mostafa = make_user("sp.sl.mostafa@example.com", ("installation_manager",))
		pm = make_user("sp.sl.pm@example.com", ("project_manager",))
		try:
			frappe.set_user(mostafa)
			with self.assertRaises(frappe.PermissionError):
				site_log.set_marketing(photo.name, 1)
			frappe.set_user(pm)
			site_log.set_marketing(photo.name, 1)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("File", photo.name, "sp_usable_for_marketing"), 1)
