"""R3 Installed capacity statement (SP-141): the stations put into operation in a period, by system
type, with the totals. The stations are dated to a past half-year, so the site's own stay out."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate

from smart_power.sp_core.services.lists import by_code
from smart_power.sp_stations import installed_capacity as ic
from smart_power.tests.utils import load_erpnext_test_data, make_customer, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"
H1 = ("2021-01-01", "2021-06-30")
CLOSED = 14  # the story's H1 with 14 closed stations
PUMPS = 10  # of them pump stations, the rest on-grid
KW, AGREED = 30.0, 300000  # each station's size and price
MOBILE = "01009998887"
PLACE, LANDMARK = "الخارجة", "بجوار المدرسة"  # a location: the first line is the place


class TestInstalledCapacity(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.pump, cls.ongrid = by_code("System Type", "PUMP"), by_code("System Type", "ONGRID")
		cls.customer = make_customer(MOBILE, "عميل القدرات")
		cls.serial = 0
		for i in range(CLOSED):
			system = cls.pump if i < PUMPS else cls.ongrid
			status = "Technically closed" if i % 2 else "Financially closed"
			cls.station(add_days(H1[0], i * 7), status, system)
		cls.station("2021-03-01", "Installing", cls.pump)  # not closed: out
		cls.station("2021-07-02", "Technically closed", cls.pump)  # the next half: out

	@classmethod
	def station(cls, operation_date, status, system_type):
		cls.serial += 1
		doc = frappe.new_doc("SP Station")
		doc.update(
			{
				"name": f"SP-IC-TEST-{cls.serial}",
				"company": COMPANY,
				"customer": cls.customer,
				"customer_name": "عميل القدرات",
				"status": status,
				"operation_date": operation_date,
				"capacity_kw_total": KW,
				"agreed_amount": AGREED,
				"location_text": "\n".join((PLACE, LANDMARK)),
			}
		)
		doc.db_insert()
		# a small second system: the main one is the one with the most kW
		for name, kw in ((system_type, KW - 1), (cls.ongrid if system_type == cls.pump else cls.pump, 1)):
			line = doc.append("systems", {"system_type": name, "capacity_kw": kw, "qty": 1})
			line.db_insert()
		return doc.name

	def statement(self, **filters):
		return ic.statement({"from_date": H1[0], "to_date": H1[1], "company": COMPANY, **filters})

	def test_h1_lists_the_14_closed_stations_and_their_total_kw(self):
		rows = self.statement()
		stations = [r for r in rows if r.get("station_name")]
		self.assertEqual(len(stations), CLOSED)
		total = rows[-1]
		self.assertTrue(total["is_total"])
		self.assertEqual((total["count"], total["capacity_kw"]), (CLOSED, CLOSED * KW))
		self.assertEqual(total["capacity_kw"], sum(r["capacity_kw"] for r in stations))
		self.assertEqual(total["total"], CLOSED * AGREED)

	def test_a_row_in_the_statements_columns(self):
		row = next(r for r in self.statement() if r.get("station_name"))
		self.assertEqual(row["operation_date"], "01/01/2021")
		self.assertEqual(row["phone"], MOBILE)
		self.assertEqual(row["price_per_kw"], AGREED / KW)
		self.assertEqual(row["location"], PLACE)

	def test_sections_by_main_system_type_in_the_lists_order(self):
		rows = self.statement()
		sections = [r["operation_date"] for r in rows if r.get("is_section")]
		self.assertEqual(len(sections), 2)
		self.assertIn(ic.label(self.pump), sections[0])  # pumps come first in the list
		first = rows.index(next(r for r in rows if r.get("is_section")))
		second = rows.index([r for r in rows if r.get("is_section")][1])
		self.assertEqual(second - first - 1, PUMPS)

	def test_the_system_type_filter(self):
		total = self.statement(system_type=self.ongrid)[-1]
		self.assertEqual(total["count"], CLOSED)  # every test station has an on-grid line
		only_pump_main = [r for r in self.statement(system_type=self.pump) if r.get("station_name")]
		self.assertEqual(len(only_pump_main), CLOSED)

	def test_the_default_period_is_the_half_year(self):
		self.assertEqual(ic.half_year("2027-03-15"), (getdate("2027-01-01"), getdate("2027-06-30")))
		self.assertEqual(ic.half_year("2027-07-01"), (getdate("2027-07-01"), getdate("2027-12-31")))

	def test_compliance_sees_the_report_and_others_do_not(self):
		report = frappe.get_doc("Report", "SP Installed Capacity")
		frappe.set_user(make_user("sp.ic.aya@example.com", ("regulatory_compliance",)))
		try:
			self.assertTrue(report.is_permitted())
			frappe.set_user(make_user("sp.ic.sales@example.com", ("showroom_sales",)))
			self.assertFalse(report.is_permitted())
		finally:
			frappe.set_user("Administrator")

	def test_the_print_has_the_company_header_and_the_statements_title(self):
		html = open(
			frappe.get_app_path(
				"smart_power", "sp_stations", "report", "sp_installed_capacity", "sp_installed_capacity.html"
			)
		).read()
		self.assertIn("filters.company", html)
		self.assertIn('dir="rtl"', html)
		self.assertIn("Installed Capacity Statement", html)
		self.assertEqual(
			frappe.db.get_value("Letter Head", {"is_default": 1}), frappe.db.get_default("letter_head")
		)
