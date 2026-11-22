"""AD1 Command dashboard (SP-138): the month's numbers, each with where a click goes, admin only.

The money is dated to a past March, so the site's own records stay out of the month's numbers.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from smart_power.dashboards import command
from smart_power.sp_core.services.review import open_review_item
from smart_power.sp_sales.quote_queue import get_queue
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
MARCH = ("2020-03-01", "2020-03-31")
CONFIRMED_MARCH = (30000, 45000)  # the month's confirmed payments
PENDING_MARCH, CONFIRMED_APRIL = 10000, 5000  # not counted
AGREED = 200000
LATE_HOURS = 30  # past the 24 h quote clock


def card(data, key):
	for c in [*(c for s in data["sections"] for c in s["cards"]), *data["attention"]]:
		if c["key"] == key:
			return c
	raise AssertionError(f"no card {key}")


class TestCommandDashboard(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		set_setting(quote_due_hours=24)
		cls.serial = 0
		for amount in CONFIRMED_MARCH:
			cls.payment(amount, "2020-03-10", "Confirmed")
		cls.payment(PENDING_MARCH, "2020-03-12", "Pending")
		cls.payment(CONFIRMED_APRIL, "2020-04-02", "Confirmed")
		cls.station("2020-03-05", "Installing", remaining=AGREED)
		cls.station("2020-02-05", "Technically closed", remaining=AGREED / 4)

	@classmethod
	def payment(cls, amount, date, status):
		cls.serial += 1
		doc = frappe.new_doc("SP Customer Payment")
		doc.update(
			{
				"name": f"SP-CD-TEST-{cls.serial}",
				"company": COMPANY,
				"amount": amount,
				"work_date": date,
				"status": status,
				"docstatus": 1,
				"creation": now_datetime(),
				"modified": now_datetime(),
			}
		)
		doc.db_insert()
		return doc.name

	@classmethod
	def station(cls, contract_date, status, remaining):
		cls.serial += 1
		doc = frappe.new_doc("SP Station")
		doc.update(
			{
				"name": f"SP-CD-ST-{cls.serial}",
				"company": COMPANY,
				"status": status,
				"contract_date": contract_date,
				"agreed_amount": AGREED,
				"remaining_amount": remaining,
			}
		)
		doc.db_insert()
		return doc.name

	def tearDown(self):
		frappe.set_user("Administrator")

	def build(self):
		return command.build(COMPANY, *(frappe.utils.getdate(d) for d in MARCH))

	def test_collected_is_the_months_confirmed_payments(self):
		self.assertEqual(card(self.build(), "collected")["value"], sum(CONFIRMED_MARCH))
		collected = card(self.build(), "collected")
		self.assertEqual(collected["route"], ["List", "SP Customer Payment"])
		self.assertEqual(collected["route_options"]["status"], "Confirmed")
		self.assertEqual(collected["route_options"]["work_date"], ["between", list(MARCH)])

	def test_contracted_and_closed_but_not_paid(self):
		data = self.build()
		self.assertEqual(card(data, "contracted")["value"], AGREED)
		closed = frappe.db.count(
			"SP Station", {"company": COMPANY, "status": "Technically closed", "remaining_amount": (">", 0)}
		)
		self.assertEqual(card(data, "closed_unpaid")["value"], closed)

	def test_requests_over_24h_open_the_queues_overdue_view(self):
		late = make_case(channel="Call").name
		fresh = make_case(channel="Call").name
		frappe.db.set_value(
			"SP Case", late, "creation", add_to_date(now_datetime(), hours=-LATE_HOURS), update_modified=False
		)
		over = card(self.build(), "over_24h")
		self.assertEqual((over["route"], over["route_options"]), (["sp-quote-queue"], {"view": "Overdue"}))
		overdue = {r["name"] for r in get_queue("Overdue")}
		self.assertIn(late, overdue)
		self.assertNotIn(fresh, overdue)
		self.assertEqual(over["value"], len(overdue))

	def test_an_open_write_off_is_on_the_attention_list(self):
		before = card(self.build(), "review_write_off")["value"]
		open_review_item(
			category="Write-off",
			reference_doctype="SP Station",
			reference_name="SP-CD-ST-5",
			summary="test write-off",
		)
		item = card(self.build(), "review_write_off")
		self.assertEqual(item["value"], before + 1)
		self.assertEqual(item["route_options"], {"category": "Write-off"})

	def test_a_confirmation_shows_at_once_despite_the_cache(self):
		with patch.object(command, "_company", return_value=COMPANY):
			# its own month: the class shares one transaction, so March stays as the others expect
			first = card(command.get("2020-05"), "collected")["value"]
			self.payment(1000, "2020-05-20", "Confirmed")
			self.assertEqual(card(command.get("2020-05"), "collected")["value"], first + 1000)

	def test_a_non_admin_gets_403(self):
		frappe.set_user(make_user("sp.cd.creator@example.com", ("quote_creator",)))
		self.assertRaises(frappe.PermissionError, command.get, "2020-03")
