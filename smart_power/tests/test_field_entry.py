"""Light field entry (SP-108): a job, an expense or money logged once, and the accounts come out right."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_finance.accounts import CUSTODY, TRANSIT, holder_account, seed_accounts
from smart_power.sp_finance.centers import PROJECTS, center, seed_centers
from smart_power.sp_finance.transfer import confirm
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import field_entry as fe
from smart_power.tests.test_bookings import employee
from smart_power.tests.test_purchase_orders import station
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
STATION_JOB, OUTSIDE_JOB, CASH_IN, FUEL_COST = 3000, 2500, 1000, 600
PHONE = "01001080108"


def list_value(list_name, code):
	found = frappe.db.get_value("SP List Value", {"list_name": list_name, "code": code})
	return (
		found
		or frappe.get_doc(
			{
				"doctype": "SP List Value",
				"list_name": list_name,
				"code": code,
				"value_ar": code,
				"value_en": code,
				"is_active": 1,
			}
		)
		.insert()
		.name
	)


def balance(account, **filters):
	rows = frappe.get_all(
		"GL Entry",
		filters={"account": account, "is_cancelled": 0, **filters},
		fields=["debit", "credit"],
	)
	return sum(flt(r.debit) - flt(r.credit) for r in rows)


class TestFieldEntry(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		seed_centers(COMPANY)
		cls.operator = make_user("sp.fe.operator@example.com", ("winch_operator",))
		cls.other = make_user("sp.fe.other@example.com", ("winch_operator",))
		cls.manager = make_user("sp.fe.manager@example.com", ("winch_manager",))
		employee(cls.operator, "SP108 Operator")
		cls.vehicle = cls.make_vehicle("SP108-WINCH", "Winch")
		cls.jumbo = cls.make_vehicle("SP108-JUMBO", "Jumbo")
		cls.job_type = list_value("Job Type", "PUMP_DOWN")
		cls.fuel = list_value("Field Expense", "FUEL")
		cls.oil = list_value("Field Expense", "OIL")
		cls.cash = list_value("Payment Method", "CASH")
		cls.instapay = list_value("Payment Method", "INSTAPAY")
		cls.official = frappe.db.get_value("Account", {"company": COMPANY, "sp_account_kind": "Official"})

	@classmethod
	def make_vehicle(cls, plate, kind):
		if not frappe.db.exists("Vehicle", plate):
			frappe.get_doc(
				{"doctype": "Vehicle", "license_plate": plate, "sp_vehicle_type": kind, "company": COMPANY}
			).insert()
		return plate

	def setUp(self):
		set_setting(account_map=[])
		fe.seed_account_map(COMPANY)
		self.services = fe._account(COMPANY, fe.SERVICES_ACCOUNT)
		self.income = fe._account(COMPANY, fe.WINCH_INCOME)
		self.running = fe._account(COMPANY, fe.RUNNING_ACCOUNT)
		self.addCleanup(frappe.set_user, "Administrator")

	def log(self, user=None, **values):
		frappe.set_user(user or self.operator)
		name = fe.save_entry({"vehicle": self.vehicle, **values})
		frappe.set_user("Administrator")
		return frappe.get_doc(fe.ENTRY, name)

	def station_job(self, **values):
		return self.log(
			entry_kind="Job",
			job_type=self.job_type,
			for_kind="Station",
			station=station().name,
			agreed_amount=STATION_JOB,
			**values,
		)

	def outside_job(self, **values):
		return self.log(
			**{
				"entry_kind": "Job",
				"job_type": self.job_type,
				"for_kind": "Outside",
				"customer_name": "SP108 Farmer",
				"customer_phone": PHONE,
				"agreed_amount": OUTSIDE_JOB,
				"received_now": CASH_IN,
				"received_method": self.cash,
				**values,
			}
		)

	def expense(self, **values):
		return self.log(
			**{
				"entry_kind": "Expense",
				"expense_type": self.fuel,
				"amount": FUEL_COST,
				"paid_from": "Custody",
				**values,
			}
		)

	def test_a_station_job_charges_the_station_and_nets_to_zero(self):
		doc = self.station_job()
		project = frappe.db.get_value("SP Station", doc.station, "project")
		self.assertEqual(balance(self.services, project=project), STATION_JOB)
		self.assertEqual(balance(self.income, voucher_no=fe.postings(doc)[0]), -STATION_JOB)
		entry = frappe.get_doc("Journal Entry", fe.postings(doc)[0])
		self.assertEqual(entry.sp_internal_charge, 1)
		self.assertEqual(sum(flt(r.debit) - flt(r.credit) for r in entry.accounts), 0)
		by_account = {r.account: r for r in entry.accounts}
		self.assertEqual(by_account[self.services].cost_center, center(PROJECTS, COMPANY))
		self.assertEqual(by_account[self.income].cost_center, doc.cost_center)

	def test_an_outside_job_leaves_the_debt_and_the_cash_with_the_driver(self):
		debtors = frappe.get_cached_value("Company", COMPANY, "default_receivable_account")
		transit = holder_account(self.operator, TRANSIT, COMPANY)
		owed, held = balance(debtors, party_type="Customer"), balance(transit)
		doc = self.outside_job()
		self.assertEqual(frappe.db.get_value("Customer", doc.customer, "sp_mobile"), PHONE)
		self.assertEqual(balance(debtors, party_type="Customer") - owed, OUTSIDE_JOB - CASH_IN)
		self.assertEqual(balance(transit) - held, CASH_IN)

	def test_a_fuel_expense_lands_on_the_vehicle_center_and_comes_off_custody(self):
		custody = holder_account(self.operator, CUSTODY, COMPANY)
		spent, held = balance(self.running), balance(custody)
		doc = self.expense()
		self.assertEqual(balance(self.running, cost_center=doc.cost_center) - spent, FUEL_COST)
		self.assertEqual(balance(custody) - held, -FUEL_COST)

	def test_a_fuel_expense_is_in_the_expenses_by_center_report(self):
		# BUG-19: the report read only direct expenses; the winch's fuel was missing
		from smart_power.sp_finance.expenses import expenses_by_center

		def fuel():
			filters = {"from_date": today(), "to_date": today(), "company": COMPANY, "center_type": "Winch"}
			return sum(
				r["amount"] for r in expenses_by_center(filters) if r["cost_center"] == doc.cost_center
			)

		doc = self.expense()
		before = fuel()
		self.expense(amount=FUEL_COST * 2)
		self.assertEqual(fuel() - before, FUEL_COST * 2)

	def test_the_same_client_uuid_synced_twice_is_one_entry(self):
		first = self.expense(client_uuid="sp108-once")
		second = self.expense(client_uuid="sp108-once")
		self.assertEqual(first.name, second.name)
		self.assertEqual(frappe.db.count(fe.ENTRY, {"client_uuid": "sp108-once"}), 1)
		self.assertEqual(len(fe.postings(first)), 1)

	def test_the_date_and_center_fill_themselves_and_a_late_entry_keeps_its_real_time(self):
		yesterday = add_days(today(), -1)
		doc = self.expense(work_date=yesterday)
		self.assertEqual(str(doc.work_date), yesterday)
		self.assertEqual(str(doc.entry_time)[: len(today())], today())
		self.assertEqual(doc.cost_center, frappe.db.get_value("Vehicle", self.vehicle, "sp_cost_center"))
		self.assertEqual(doc.logged_by, self.operator)

	def test_changing_the_amount_reverses_and_posts_again(self):
		spent = balance(self.running)
		doc = self.expense()
		doc.amount = FUEL_COST * 2
		doc.save()
		self.assertEqual(len(fe.postings(doc)), 1)
		self.assertEqual(balance(self.running) - spent, FUEL_COST * 2)

	def test_an_oil_change_resets_the_reminder(self):
		km = frappe.db.get_value("Vehicle", self.vehicle, "sp_odometer_km") + 500
		self.expense(expense_type=self.oil, odometer=km)
		row = frappe.db.get_value("Vehicle", self.vehicle, ["sp_odometer_km", "sp_last_oil_km"], as_dict=True)
		self.assertEqual((row.sp_odometer_km, row.sp_last_oil_km), (km, km))

	def test_oil_needs_the_odometer(self):
		with self.assertRaises(frappe.MandatoryError):
			self.expense(expense_type=self.oil)

	def test_a_deposit_waits_for_the_admin(self):
		self.outside_job()
		transit = holder_account(self.operator, TRANSIT, COMPANY)
		held = balance(transit)
		doc = self.log(
			entry_kind="Money",
			money_kind="Deposit",
			amount=CASH_IN,
			to_account=self.official,
			photo="/files/sp108.png",
		)
		self.assertEqual(frappe.db.get_value("SP Transfer", doc.transfer, "status"), "Pending")
		self.assertEqual(balance(transit), held)
		confirm(doc.transfer)
		self.assertEqual(balance(transit), held - CASH_IN)

	def test_money_sent_to_a_company_account_is_not_official_until_confirmed(self):
		before = balance(self.official)
		doc = self.outside_job(
			received_method=self.instapay, to_account=self.official, photo="/files/sp108.png"
		)
		self.assertEqual(frappe.db.get_value("SP Transfer", doc.transfer, "status"), "Pending")
		self.assertEqual(balance(self.official), before)

	def test_money_received_later_cannot_pass_what_is_open(self):
		job = self.outside_job()
		values = {"entry_kind": "Money", "money_kind": "Received", "related_job": job.name}
		self.log(amount=OUTSIDE_JOB - CASH_IN, received_method=self.cash, **values)
		with self.assertRaises(frappe.ValidationError):
			self.log(amount=1, received_method=self.cash, **values)

	def test_an_operator_sees_only_their_own_entries(self):
		doc = self.expense()
		self.assertFalse(fe.has_permission(doc, "read", self.other))
		self.assertTrue(fe.has_permission(doc, "read", self.manager))
		self.assertIn(self.other, fe.query_conditions(self.other))
		self.assertEqual(fe.query_conditions(self.manager), "")

	def test_only_the_manager_logs_for_someone_else(self):
		with self.assertRaises(frappe.PermissionError):
			self.expense(on_behalf_of=self.other)
		custody = holder_account(self.operator, CUSTODY, COMPANY)
		held = balance(custody)
		doc = self.expense(user=self.manager, on_behalf_of=self.operator)
		self.assertEqual(balance(custody) - held, -FUEL_COST)
		self.assertEqual(doc.logged_by, self.manager)

	def test_a_logged_booking_is_done_and_opens_prefilled(self):
		booking = frappe.get_doc(
			{
				"doctype": "SP Vehicle Booking",
				"for_kind": "Outside",
				"customer_name": "SP108 Booked",
				"customer_phone": "01001080109",
				"vehicle": self.vehicle,
				"job_type": self.job_type,
				"place": "SP108 Farm",
				"planned_date": today(),
				"agreed_amount": OUTSIDE_JOB,
			}
		).insert()
		doc = self.log(entry_kind="Job", booking=booking.name)
		self.assertEqual((doc.customer_name, flt(doc.agreed_amount)), ("SP108 Booked", OUTSIDE_JOB))
		self.assertEqual(frappe.db.get_value("SP Vehicle Booking", booking.name, "status"), "Done")
		with self.assertRaises(frappe.ValidationError):
			self.log(entry_kind="Job", booking=booking.name)

	def test_the_jumbo_car_earns_on_its_own_account(self):
		doc = self.log(
			vehicle=self.jumbo,
			entry_kind="Job",
			job_type=self.job_type,
			for_kind="Station",
			station=station().name,
			agreed_amount=STATION_JOB,
		)
		accounts = {r.account for r in frappe.get_doc("Journal Entry", fe.postings(doc)[0]).accounts}
		self.assertIn(fe._account(COMPANY, fe.JUMBO_INCOME), accounts)

	def test_the_pickers_offer_official_accounts_and_operators_only(self):
		frappe.set_user(self.operator)
		accounts = [r[0] for r in fe.official_account_query("Account", "", "name", 0, 50)]
		self.assertIn(self.official, accounts)
		self.assertNotIn(holder_account(self.operator, TRANSIT, COMPANY), accounts)
		with self.assertRaises(frappe.PermissionError):
			fe.operator_query("User", "", "name", 0, 50)
		frappe.set_user(self.manager)
		people = [r[0] for r in fe.operator_query("User", "sp.fe", "name", 0, 50)]
		self.assertIn(self.operator, people)
		self.assertNotIn(self.manager, people)

	def test_a_new_customer_brings_no_message_to_the_operator(self):
		programmes = "erpnext.selling.doctype.customer.customer.get_loyalty_programs"
		frappe.clear_messages()
		with patch(programmes, return_value=["SP108 A", "SP108 B"]):
			self.outside_job(customer_phone="01001080110", customer_name="SP108 Quiet")
		self.assertEqual(frappe.get_message_log(), [])
