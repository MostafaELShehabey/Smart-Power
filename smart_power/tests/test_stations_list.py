"""S1 Stations list (SP-77): the views, the columns, the totals, and no money for the site."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.lists import seed_list_views, totals, views_for
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_station import COMPANY
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user

load_erpnext_test_data()

STATION = "SP Station"
COLUMNS = [
	"customer_name",
	"systems_summary",
	"capacity_kw_total",
	"hp_total",
	"region",
	"financing_type",
	"status",
	"execution_owner",
	"collection_owner",
	"contract_date",
	"operation_date",
	"agreed_amount",
	"paid_amount",
	"remaining_amount",
	"next_due_date",
]
MONEY = ["agreed_amount", "paid_amount", "remaining_amount"]


class TestStationsList(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_list_views()
		cls.amira = make_user("sp.sl.amira@example.com", ("project_manager",))
		cls.mostafa = make_user("sp.sl.mostafa@example.com", ("installation_manager", "site_receiver"))
		cls.system = frappe.db.get_value("SP List Value", {"list_name": "System Type"}, "name")

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def station(self, rate, **values):
		quote = make_quotation(rate=rate, valid_days=3)
		quote.submit()
		frappe.db.set_value("SP Case", quote.sp_case, "accepted_quotation", quote.name)
		frappe.set_user(self.amira)
		try:
			doc = frappe.get_doc({"doctype": STATION, "case": quote.sp_case, "company": COMPANY}).insert()
		finally:
			frappe.set_user("Administrator")
		if values:
			frappe.db.set_value(STATION, doc.name, values)
		return frappe.get_doc(STATION, doc.name)

	def test_the_list_has_the_story_columns_in_its_order(self):
		import json

		from smart_power.sp_stations.setup import LIST_COLUMNS, seed_list_settings

		meta = frappe.get_meta(STATION)
		self.assertEqual({f.fieldname for f in meta.fields if f.in_list_view}, set(COLUMNS))
		seed_list_settings()
		order = [
			f["fieldname"] for f in json.loads(frappe.db.get_value("List View Settings", STATION, "fields"))
		]
		self.assertEqual(order, list(LIST_COLUMNS))
		self.assertEqual(meta.title_field, "customer_name")  # the first column

	def test_the_systems_and_hp_columns_follow_the_systems_table(self):
		if not self.system:
			self.skipTest("no System Type list value on this site")
		doc = self.station(1000)
		doc.set("systems", [{"system_type": self.system, "hp": 10, "qty": 2, "capacity_kw": 7.5}])
		doc.save()
		label = frappe.db.get_value("SP List Value", self.system, "value_ar") or self.system
		self.assertEqual((doc.hp_total, doc.capacity_kw_total), (20, 15))
		self.assertIn(label, doc.systems_summary)

	def test_the_story_views_in_order(self):
		views = [v["label"] for v in views_for(self.amira)[STATION]]
		self.assertEqual(views, ["Mine", "Open", "Installing", "Collecting", "Overdue", "Closed", "All"])

	def test_the_overdue_view_lists_only_overdue_stations_with_their_remaining_total(self):
		late = self.station(30000, has_overdue=1)
		self.station(50000)
		overdue = next(v for v in views_for(self.amira)[STATION] if v["label"] == "Overdue")
		frappe.set_user(self.amira)
		listed = frappe.get_list(STATION, filters=overdue["filters"], pluck="name")
		sums = totals(STATION, overdue["filters"], MONEY)
		frappe.set_user("Administrator")
		self.assertIn(late.name, listed)
		self.assertTrue(all(frappe.db.get_value(STATION, n, "has_overdue") for n in listed))
		expected = sum(frappe.db.get_value(STATION, n, "remaining_amount") for n in listed)
		self.assertEqual(sums["remaining_amount"], expected)

	def test_collecting_is_technically_closed_with_money_remaining(self):
		collecting = self.station(40000, status="Technically closed")
		self.station(20000, status="Technically closed", remaining_amount=0)
		view = next(v for v in views_for(self.amira)[STATION] if v["label"] == "Collecting")
		frappe.set_user(self.amira)
		listed = frappe.get_list(STATION, filters=view["filters"], pluck="name")
		frappe.set_user("Administrator")
		self.assertIn(collecting.name, listed)
		self.assertTrue(all(frappe.db.get_value(STATION, n, "remaining_amount") > 0 for n in listed))

	def test_mostafa_sees_every_station_and_no_money(self):
		doc = self.station(60000)
		frappe.set_user(self.mostafa)
		listed = frappe.get_list(STATION, pluck="name")  # every station is his (owner, 2026-11-21)
		sums = totals(STATION, [], MONEY)
		views = [v["label"] for v in views_for(self.mostafa)[STATION]]
		readable = set(frappe.model.get_permitted_fields(STATION))
		frappe.set_user("Administrator")
		self.assertIn(doc.name, listed)
		self.assertEqual(sums, {})
		self.assertNotIn("Collecting", views)  # it filters on an amount he cannot read
		self.assertFalse(set(MONEY) & readable)
