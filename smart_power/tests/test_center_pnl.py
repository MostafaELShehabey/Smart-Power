"""R4 Center P&L (SP-142): each center's profit, internal charges cancelling out in the company total."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from smart_power.sp_finance import center_pnl as pnl
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import INDIRECT, PROJECTS, SHOWROOM, WINCH, seed_centers
from smart_power.sp_finance.indirect_split import EVENT as SPLIT_EVENT
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_winch import field_entry as fe
from smart_power.tests.test_bookings import employee
from smart_power.tests.test_field_entry import list_value
from smart_power.tests.test_purchase_orders import station
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
SALES, CASH, COST = "Sales - _TC", "Cash - _TC", "Cost of Goods Sold - _TC"
WINCH_JOB, SHOWROOM_SALE, POOL = 3000, 4500, 1200  # the story's 3,000 winch job; demo amounts


class TestCenterPnl(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		cls.centers = seed_centers(COMPANY)
		set_setting(**{f"center_{key}": name for key, name in cls.centers.items()})  # the vehicle takes Winch
		cls.operator = make_user("sp.pnl.operator@example.com", ("winch_operator",))
		employee(cls.operator, "SP142 Operator")
		cls.vehicle = "SP142-WINCH"
		if not frappe.db.exists("Vehicle", cls.vehicle):
			frappe.get_doc(
				{
					"doctype": "Vehicle",
					"license_plate": cls.vehicle,
					"sp_vehicle_type": "Winch",
					"company": COMPANY,
				}
			).insert()
		cls.job_type = list_value("Job Type", "PUMP_DOWN")

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_setting(account_map=[], **{f"center_{key}": name for key, name in self.centers.items()})
		fe.seed_account_map(COMPANY)

	def report(self, **filters):
		rows = pnl.summary({"company": COMPANY, **filters})
		by_key = {r["center_key"]: r for r in rows if not r["indent"]}
		by_station = {r["station"]: r for r in rows if r["indent"]}
		return by_key, by_station

	def entry(self, lines, event=None):
		doc = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COMPANY,
				"posting_date": today(),
				"sp_posting_event": event,
				"accounts": [
					{
						"account": account,
						"cost_center": cost_center,
						"debit_in_account_currency": max(amount, 0),
						"credit_in_account_currency": max(-amount, 0),
					}
					for account, cost_center, amount in lines
				],
			}
		).insert()
		doc.submit()
		return doc

	def winch_job(self):
		target = station()
		frappe.set_user(self.operator)
		fe.save_entry(
			{
				"vehicle": self.vehicle,
				"entry_kind": "Job",
				"job_type": self.job_type,
				"for_kind": "Station",
				"station": target.name,
				"agreed_amount": WINCH_JOB,
			}
		)
		frappe.set_user("Administrator")
		return target.name

	def test_a_3000_station_winch_job_counts_in_both_centers_and_not_in_the_company_profit(self):
		before, _stations = self.report()
		name = self.winch_job()
		after, stations = self.report()

		def delta(key, field):
			return after[key][field] - before[key][field]

		self.assertEqual((delta(WINCH, "revenue"), delta(WINCH, "internal_in")), (WINCH_JOB, WINCH_JOB))
		self.assertEqual((stations[name]["cost"], stations[name]["internal_out"]), (WINCH_JOB, WINCH_JOB))
		self.assertEqual(delta(PROJECTS, "cost"), WINCH_JOB)
		self.assertEqual(delta(pnl.ELIMINATION, "revenue"), -WINCH_JOB)
		self.assertEqual(delta(pnl.ELIMINATION, "profit"), 0)
		self.assertEqual(delta(pnl.TOTAL, "profit"), 0)  # company profit unchanged by it
		self.assertEqual(delta(pnl.TOTAL, "revenue"), 0)  # and it is not company revenue
		lines = pnl.lines({"company": COMPANY, "center": PROJECTS, "station": name, "kind": "Direct Cost"})
		self.assertEqual([(line.amount, line.internal) for line in lines], [(WINCH_JOB, 1)])

	def test_showroom_revenue_drills_into_its_gl_lines(self):
		sale = self.entry(
			[(CASH, self.centers[SHOWROOM], SHOWROOM_SALE), (SALES, self.centers[SHOWROOM], -SHOWROOM_SALE)]
		)
		after, _stations = self.report()
		lines = pnl.lines({"company": COMPANY, "center": SHOWROOM, "kind": "Revenue"})
		ours = [line for line in lines if line.voucher_no == sale.name]
		self.assertEqual([(line.account, line.amount) for line in ours], [(SALES, SHOWROOM_SALE)])
		self.assertGreaterEqual(after[SHOWROOM]["revenue"], SHOWROOM_SALE)
		self.assertFalse(any(line.root_type != "Income" for line in lines))

	def test_the_indirect_pool_nets_to_zero_after_the_split(self):
		before, _stations = self.report()
		self.entry([(COST, self.centers[INDIRECT], POOL), (CASH, self.centers[INDIRECT], -POOL)])
		self.entry([(COST, self.centers[SHOWROOM], POOL), (COST, self.centers[INDIRECT], -POOL)], SPLIT_EVENT)
		after, _stations = self.report()
		pool = {f: after[INDIRECT][f] - before[INDIRECT][f] for f in ("cost", "indirect", "profit")}
		self.assertEqual(pool, {"cost": POOL, "indirect": -POOL, "profit": 0})
		self.assertEqual(after[SHOWROOM]["indirect"] - before[SHOWROOM]["indirect"], POOL)
		self.assertEqual(after[pnl.TOTAL]["profit"] - before[pnl.TOTAL]["profit"], -POOL)

	def test_a_child_center_counts_for_its_parent(self):
		frappe.db.set_value(
			"Cost Center", self.centers[WINCH], "is_group", 1
		)  # a parent, as the admin makes it
		self.addCleanup(frappe.db.set_value, "Cost Center", self.centers[WINCH], "is_group", 0)
		child = frappe.db.get_value("Cost Center", {"cost_center_name": "SP142 Winch 2", "company": COMPANY})
		if not child:
			child = (
				frappe.get_doc(
					{
						"doctype": "Cost Center",
						"cost_center_name": "SP142 Winch 2",
						"company": COMPANY,
						"parent_cost_center": self.centers[WINCH],
						"is_group": 0,
					}
				)
				.insert()
				.name
			)
		before, _stations = self.report()
		self.entry([(CASH, child, POOL), (SALES, child, -POOL)])
		after, _stations = self.report()
		self.assertEqual(after[WINCH]["revenue"] - before[WINCH]["revenue"], POOL)
