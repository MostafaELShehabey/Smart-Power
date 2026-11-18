"""Vehicles (SP-106): the oil change arithmetic, the driver's note and each vehicle's center."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_finance.centers import JUMBO, center, seed_centers
from smart_power.sp_finance.queries import center_picker
from smart_power.sp_winch import vehicles as v
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting
from smart_power.www.sp_field import get_context

load_erpnext_test_data()

COMPANY = "_Test Company"


def vehicle(plate, kind=v.JUMBO_TYPE, **kw):
	return frappe.get_doc(
		{
			"doctype": v.VEHICLE,
			"license_plate": plate,
			"sp_vehicle_type": kind,
			"sp_odometer_km": 84500,
			"sp_oil_interval_km": 5000,
			"sp_last_oil_km": 80000,
			"company": COMPANY,
			**kw,
		}
	).insert()


class TestVehicles(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_centers(COMPANY)
		cls.driver = make_user("sp.veh.driver@example.com", ("driver",))
		cls.manager = make_user("sp.veh.manager@example.com", ("winch_manager",))
		set_setting(oil_interval_km=5000, oil_alert_km=200)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_next_oil_change_and_what_the_driver_sees(self):
		doc = vehicle("SP106-A", sp_driver_user=self.driver)
		self.assertEqual((doc.sp_next_oil_km, v.km_to_oil(doc)), (85000, 500))
		frappe.set_user(self.driver)
		note = v.driver_oil_note()
		self.assertEqual((note["vehicle"], note["km_left"], note["overdue"]), ("SP106-A", 500, False))
		context = frappe._dict()
		get_context(context)
		self.assertEqual(context.oil["km_left"], 500)

	def test_the_winch_and_the_jumbo_car_post_to_their_own_centers(self):
		doc = vehicle("SP106-B")
		self.assertEqual(doc.sp_cost_center, center(JUMBO, COMPANY))

	def test_a_new_vehicle_takes_the_center_the_admin_added_and_it_joins_the_picker(self):
		self.assertRaises(frappe.MandatoryError, vehicle, "SP106-C", v.OTHER_TYPE)
		root = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 1})
		added = frappe.get_doc(
			{
				"doctype": "Cost Center",
				"cost_center_name": "Winch 2",
				"company": COMPANY,
				"parent_cost_center": root,
			}
		).insert()
		before = [r[0] for r in center_picker("Cost Center", "", "name", 0, 50, {"company": COMPANY})]
		self.assertNotIn(added.name, before)
		vehicle("SP106-D", v.OTHER_TYPE, sp_cost_center=added.name)
		after = [r[0] for r in center_picker("Cost Center", "", "name", 0, 50, {"company": COMPANY})]
		self.assertIn(added.name, after)

	def test_the_default_interval_comes_from_the_settings(self):
		doc = vehicle("SP106-E", sp_oil_interval_km=0)
		self.assertEqual(doc.sp_oil_interval_km, 5000)

	def test_an_oil_change_resets_the_reminder(self):
		doc = vehicle("SP106-F")
		v.record_odometer(doc.name, 84900)
		self.assertEqual(frappe.db.get_value(v.VEHICLE, doc.name, "sp_next_oil_km"), 85000)
		v.record_odometer(doc.name, 85100, oil_changed=True)
		doc.reload()
		self.assertEqual((doc.sp_last_oil_km, doc.sp_next_oil_km), (85100, 90100))

	def test_the_odometer_cannot_go_back(self):
		doc = vehicle("SP106-G")
		self.assertRaises(frappe.ValidationError, v.record_odometer, doc.name, 100)

	def test_the_alert_goes_out_once_for_each_oil_change(self):
		doc = vehicle("SP106-H", sp_odometer_km=84850, sp_driver_user=self.driver)
		far = vehicle("SP106-I", sp_odometer_km=81000)
		v.check_oil_due()
		subject = {"for_user": self.driver, "document_name": doc.name}
		self.assertEqual(frappe.db.count("Notification Log", subject), 1)
		v.check_oil_due()
		self.assertEqual(frappe.db.count("Notification Log", subject), 1)
		self.assertFalse(frappe.db.exists("Notification Log", {"document_name": far.name}))
