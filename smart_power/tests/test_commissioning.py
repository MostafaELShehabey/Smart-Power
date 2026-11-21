"""PR1 programming and commissioning (SP-97): the operation date starts the warranty and asks
أميرة to close the station technically; an unchecked item refuses the submit."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.setup.seed import seed_list_values
from smart_power.sp_site import commissioning as com
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"
PUMP, ONGRID = "System Type-PUMP", "System Type-ONGRID"
INVT = "Inverter Brand-INVT"
INVERTER = "_Test Item"


class TestCommissioning(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_list_values()
		com.seed_commissioning_templates()
		cls.amira = make_user("sp.com.amira@example.com", ("project_manager",))

	def station(self, *systems):
		return frappe.get_doc(
			{
				"doctype": "SP Station",
				"customer": "_Test Customer",
				"company": COMPANY,
				"systems": [{"system_type": t, "capacity_kw": 10, "qty": 1} for t in systems or (PUMP,)],
			}
		).insert()

	def commissioning(self, station, row=0, operation_date="2027-04-15", done=True, **kw):
		doc = frappe.get_doc(
			{
				"doctype": "SP Commissioning",
				"station": station.name,
				"system_row": station.systems[row].name,
				"operation_date": operation_date,
				"inverter_brand": INVT,
				"inverter_model": "GD100",
				"inverter_serial": "INV-0001",
				"components": [
					{
						"component_type": "Inverter",
						"item": INVERTER,
						"serial": "INV-0001",
						"warranty_months": 24,
					}
				],
				**kw,
			}
		).insert()
		if done:
			for row in doc.checklist:
				row.done = 1
			doc.save()
		return doc

	def close_tasks(self, station):
		return frappe.get_all(
			"SP Task",
			{"task_type": com.TECH_CLOSE_TASK, "reference_name": station.name, "status": "Open"},
			pluck="assigned_to",
		)

	def test_operation_date_starts_the_warranty_and_asks_to_close(self):
		st = self.station()
		doc = self.commissioning(st)
		doc.submit()
		self.assertEqual(str(frappe.db.get_value("SP Station", st.name, "operation_date")), "2027-04-15")
		self.assertEqual(str(doc.components[0].warranty_end), "2029-04-15")
		self.assertIn(self.amira, self.close_tasks(st))

	def test_an_unchecked_item_is_refused_by_name(self):
		st = self.station()
		doc = self.commissioning(st)
		left = doc.checklist[2]
		left.done = 0
		doc.save()
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.submit()
		self.assertIn(left.item, str(caught.exception))
		self.assertFalse(frappe.db.get_value("SP Station", st.name, "operation_date"))

	def test_the_pump_template_is_the_starting_checklist(self):
		doc = self.commissioning(self.station(), done=False)
		items = [r.item for r in doc.checklist]
		pump = com.template(PUMP)
		self.assertEqual(len(items), len(pump["checklist"]))
		self.assertIn("Flow", [r.param for r in doc.readings])

	def test_warranty_months_from_the_item(self):
		frappe.db.set_value("Item", INVERTER, "sp_warranty_years", 2)
		self.assertEqual(com.item_warranty_months(INVERTER), 24)
		frappe.db.set_value("Item", INVERTER, {"sp_warranty_years": 0, "warranty_period": "365"})
		self.assertEqual(com.item_warranty_months(INVERTER), 12)
		frappe.db.set_value("Item", INVERTER, {"sp_warranty_years": 2, "warranty_period": None})
		doc = self.commissioning(
			self.station(), components=[{"component_type": "Inverter", "item": INVERTER}]
		)
		self.assertEqual(doc.components[0].warranty_months, 24)

	def test_one_commissioning_per_system(self):
		st = self.station()
		self.commissioning(st)
		with self.assertRaises(frappe.DuplicateEntryError):
			self.commissioning(st)

	def test_every_system_before_the_close_task(self):
		st = self.station(PUMP, ONGRID)
		self.commissioning(st, 0, "2027-04-10").submit()
		self.assertEqual(self.close_tasks(st), [])
		self.assertEqual(str(frappe.db.get_value("SP Station", st.name, "operation_date")), "2027-04-10")
		self.commissioning(st, 1, "2027-04-15").submit()
		self.assertEqual(str(frappe.db.get_value("SP Station", st.name, "operation_date")), "2027-04-15")
		self.assertIn(self.amira, self.close_tasks(st))

	def test_settings_file_of_another_model_is_refused(self):
		from smart_power.sp_site import settings_files as sf

		f = frappe.get_doc(
			{"doctype": "File", "file_name": "gd20.par", "content": b"P01=1\n", "is_private": 1}
		).insert()
		other = sf.upload(INVT, "GD20", f.file_url)
		with self.assertRaises(frappe.ValidationError):
			self.commissioning(self.station(), settings_file=other["name"])

	def test_cancel_puts_the_operation_date_back(self):
		st = self.station()
		doc = self.commissioning(st)
		doc.submit()
		doc.cancel()
		self.assertFalse(frappe.db.get_value("SP Station", st.name, "operation_date"))
		self.assertEqual(self.close_tasks(st), [])

	def test_closed_station_cancel_is_for_the_admin(self):
		st = self.station()
		doc = self.commissioning(st)
		doc.submit()
		frappe.db.set_value("SP Station", st.name, "status", "Technically closed")
		mostafa = make_user("sp.com.mostafa@example.com", ("installation_manager",))
		frappe.set_user(mostafa)
		try:
			with self.assertRaises(frappe.ValidationError) as caught:
				frappe.get_doc("SP Commissioning", doc.name).cancel()
			self.assertIn("only the admin", str(caught.exception))
		finally:
			frappe.set_user("Administrator")
