"""Customer balances AR1 and the statement (SP-120)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_finance import balances
from smart_power.sp_finance.report.sp_customer_balances.sp_customer_balances import execute
from smart_power.sp_stations.station import record_write_off
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_station import COMPANY, WRITE_OFF_MAP, receive
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()


class TestBalances(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		set_setting(account_map=[WRITE_OFF_MAP])
		self.pm = make_user("sp.bal.pm@example.com", ("project_manager",))
		self.collector = make_user("sp.bal.collector@example.com", ("collection_officer",))

	def tearDown(self):
		frappe.set_user("Administrator")

	def station(self, rate: float):
		quote = make_quotation(rate=rate, valid_days=3)
		quote.submit()
		frappe.db.set_value("SP Case", quote.sp_case, "accepted_quotation", quote.name)
		frappe.set_user(self.pm)
		try:
			name = (
				frappe.get_doc({"doctype": "SP Station", "case": quote.sp_case, "company": COMPANY})
				.insert()
				.name
			)
		finally:
			frappe.set_user("Administrator")
		return frappe.get_doc("SP Station", name)

	def test_two_stations_two_rows_matching_their_chips(self):
		a, b = self.station(200000), self.station(80000)
		self.assertEqual(a.customer, b.customer)
		receive(a, 50000)
		receive(b, 30000)
		_columns, rows = execute({"customer": a.customer})
		mine = {r["station"]: r for r in rows if r["station"] in (a.name, b.name)}
		self.assertEqual(len(mine), 2)
		for st in (a, b):
			st.reload()
			row = mine[st.name]
			self.assertEqual(
				(row["agreed"], row["paid"], row["remaining"]),
				(flt(st.agreed_amount), flt(st.paid_amount), flt(st.remaining_amount)),
			)
		self.assertEqual(sum(r["remaining"] for r in mine.values()), 150000 + 50000)

	def test_statement_running_balance_ends_at_remaining(self):
		st = self.station(200000)
		receive(st, 50000)
		receive(st, 20000)
		record_write_off(st.name, 10000, "خصم تسوية")
		st.reload()
		lines = balances.statement_lines(st.name)
		self.assertEqual((lines[0]["debit"], lines[0]["credit"]), (200000, 0))
		self.assertEqual(len(lines), 4)  # the contract, two payments, the write-off
		self.assertEqual(lines[-1]["balance"], flt(st.remaining_amount))
		self.assertEqual(lines[-1]["balance"], 120000)
		html = frappe.get_print("SP Station", st.name, "SP Customer Statement")
		self.assertIn(st.name, html)

	def test_overdue_is_what_the_past_instalments_still_lack(self):
		st = self.station(200000)
		rows = frappe.get_all("Payment Schedule", {"parent": st.quotation_accepted}, pluck="name")
		self.assertTrue(rows)
		# the whole amount fell due last week
		frappe.db.set_value("Payment Schedule", rows[0], "due_date", add_days(today(), -7))
		receive(st, 50000)
		st.reload()
		self.assertEqual(balances.overdue(st), 150000)

	def test_a_collection_officer_sees_only_their_stations(self):
		a, b = self.station(200000), self.station(80000)
		frappe.db.set_value("SP Station", a.name, "collection_owner", self.collector)
		frappe.set_user(self.collector)
		_columns, rows = execute({})
		self.assertEqual({r["station"] for r in rows}, {a.name})
		self.assertTrue(frappe.has_permission("SP Station", "print", doc=a.name))
		self.assertFalse(frappe.has_permission("SP Station", "read", doc=b.name))
