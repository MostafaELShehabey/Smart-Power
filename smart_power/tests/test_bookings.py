"""Winch and car bookings (SP-107): a job is planned before it happens, the operator sees it on the
day, and a contract's winch line opens an expected booking."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_finance.centers import JUMBO, center, seed_centers
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import bookings as b
from smart_power.tests.test_purchase_orders import station
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user
from smart_power.www.sp_field import get_context

load_erpnext_test_data()

COMPANY = "_Test Company"
WINCH_AMOUNT = 3000


def employee(user, name):
	found = frappe.db.get_value("Employee", {"user_id": user})
	return (
		found
		or frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": name,
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": "2020-01-01",
				"company": COMPANY,
				"status": "Active",
				"user_id": user,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestBookings(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_centers(COMPANY)
		cls.manager = make_user("sp.bk.manager@example.com", ("winch_manager",))
		cls.driver = make_user("sp.bk.operator@example.com", ("winch_operator",))
		cls.other = make_user("sp.bk.other@example.com", ("site_receiver",))
		cls.amira = make_user("sp.bk.amira@example.com", ("project_manager", "contract_manager"))
		cls.operator = employee(cls.driver, "SP107 Operator")
		plate = "SP107-WINCH"
		if not frappe.db.exists("Vehicle", plate):
			frappe.get_doc(
				{"doctype": "Vehicle", "license_plate": plate, "sp_vehicle_type": "Winch", "company": COMPANY}
			).insert()
		cls.vehicle = plate
		cls.job = (
			frappe.db.get_value("SP List Value", {"list_name": "Job Type"})
			or frappe.get_doc(
				{
					"doctype": "SP List Value",
					"list_name": "Job Type",
					"code": "SP107",
					"value_ar": "نقل",
					"value_en": "Transport",
					"is_active": 1,
				}
			)
			.insert()
			.name
		)

	def setUp(self):
		frappe.db.delete(b.BOOKING)  # the class shares one transaction

	def tearDown(self):
		frappe.set_user("Administrator")

	def outside(self, **kw):
		return frappe.get_doc(
			{
				"doctype": b.BOOKING,
				"for_kind": b.FOR_OUTSIDE,
				"customer_name": "عميل خارجي",
				"customer_phone": "01000000000",
				"vehicle": self.vehicle,
				"job_type": self.job,
				"place": "المنيا",
				"planned_date": today(),
				"operator": self.operator,
				"agreed_amount": 1500,
				**kw,
			}
		).insert()

	def test_a_contract_with_a_winch_line_opens_an_expected_booking(self):
		q = make_quotation(rate=100000, save=False)
		q.append("items", {"sp_line_kind": "Winch", "qty": 1, "rate": WINCH_AMOUNT})
		q.insert().submit()
		approve_version(q.name)
		frappe.set_user(self.amira)
		st = make_contract(q.sp_case)["station"]
		frappe.set_user("Administrator")
		row = frappe.get_all(
			b.BOOKING, {"station": st}, ["status", "source", "agreed_amount", "vehicle", "for_kind"]
		)
		self.assertEqual(len(row), 1)
		self.assertEqual(
			(row[0].status, row[0].source, flt(row[0].agreed_amount)), (b.EXPECTED, b.CONTRACT, WINCH_AMOUNT)
		)
		self.assertEqual((row[0].vehicle, row[0].for_kind), (self.vehicle, b.FOR_STATION))
		b.expect_winch_job(st, WINCH_AMOUNT + 500)  # the contract is made again
		rows = frappe.get_all(b.BOOKING, {"station": st}, pluck="agreed_amount")
		self.assertEqual([flt(a) for a in rows], [WINCH_AMOUNT + 500])

	def test_the_operator_sees_a_job_under_todays_jobs_on_its_day(self):
		frappe.set_user(self.manager)
		doc = self.outside()
		tomorrow = self.outside(planned_date=add_days(today(), 1))
		frappe.set_user("Administrator")
		self.assertEqual((doc.status, tomorrow.status), (b.BOOKED, b.BOOKED))
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": self.driver, "document_name": doc.name})
		)
		frappe.set_user(self.driver)
		jobs = b.todays_jobs()
		self.assertEqual([j["name"] for j in jobs], [doc.name])
		self.assertEqual((jobs[0]["place"], jobs[0]["amount"]), ("المنيا", 1500))
		context = frappe._dict()
		get_context(context)
		self.assertEqual([j["name"] for j in context.jobs], [doc.name])
		with patch("smart_power.sp_winch.bookings.nowdate", return_value=tomorrow.planned_date):
			self.assertEqual([j["name"] for j in b.todays_jobs()], [tomorrow.name])

	def test_todays_job_carries_what_log_this_job_fills(self):
		"""BUG-16: the phone form gets the booking's job type, customer, phone and price."""
		doc = self.outside()
		frappe.set_user(self.driver)
		job = next(j for j in b.todays_jobs() if j["name"] == doc.name)
		self.assertEqual(
			(job["job_type"], job["for_kind"], job["customer_name"], job["phone"], job["amount"]),
			(self.job, b.FOR_OUTSIDE, "عميل خارجي", "01000000000", 1500),
		)

	def test_a_booking_without_an_operator_stays_expected(self):
		doc = self.outside(operator=None)
		self.assertEqual(doc.status, b.EXPECTED)
		doc.operator = self.operator
		doc.save()
		self.assertEqual(doc.status, b.BOOKED)

	def test_the_vehicles_driver_is_the_default_operator(self):
		frappe.db.set_value("Vehicle", self.vehicle, "sp_driver_user", self.driver)
		doc = self.outside(operator=None)
		frappe.db.set_value("Vehicle", self.vehicle, "sp_driver_user", None)
		self.assertEqual((doc.operator, doc.status), (self.operator, b.BOOKED))

	def test_a_station_job_takes_the_winch_line_of_its_quote(self):
		st = station()
		frappe.db.set_value("SP Station", st.name, "winch_expected_amount", WINCH_AMOUNT)
		doc = frappe.get_doc(
			{"doctype": b.BOOKING, "for_kind": b.FOR_STATION, "station": st.name, "customer_name": "x"}
		).insert()
		self.assertEqual((flt(doc.agreed_amount), doc.customer_name), (WINCH_AMOUNT, None))

	def test_smart_powers_own_use_names_the_requesting_center(self):
		base = {"doctype": b.BOOKING, "for_kind": b.FOR_CENTER}
		self.assertRaises(frappe.MandatoryError, frappe.get_doc({**base}).insert)
		doc = frappe.get_doc({**base, "internal_center": center(JUMBO, COMPANY)}).insert()
		self.assertEqual(doc.internal_center, center(JUMBO, COMPANY))

	def test_an_outside_job_needs_the_customer(self):
		self.assertRaises(frappe.MandatoryError, self.outside, customer_phone=None)

	def test_a_cancelled_booking_leaves_todays_jobs(self):
		doc = self.outside()
		frappe.set_user(self.manager)
		b.cancel_booking(doc.name)
		frappe.set_user(self.driver)
		self.assertEqual(b.todays_jobs(), [])

	def test_only_the_winch_manager_cancels(self):
		doc = self.outside()
		frappe.set_user(self.other)
		self.assertRaises(frappe.PermissionError, b.cancel_booking, doc.name)

	def test_a_finished_job_cannot_be_cancelled(self):
		doc = self.outside()
		doc.db_set("status", b.DONE)
		self.assertRaises(frappe.ValidationError, b.cancel_booking, doc.name)
