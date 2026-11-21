"""A16 Indirect cost split (SP-124): the month's pool into the stations closed that month."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, flt, today

from smart_power.sp_core.setup.seed import seed_list_values
from smart_power.sp_finance import centers
from smart_power.sp_finance import expenses as ex
from smart_power.sp_finance import indirect_split as isp
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_stations.costing import actual_cost
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

COMPANY, STATION = "_Test Company", "SP Station"
SHARES = (15000, 20000, 15000)
SHOWROOM_SHARE = 10000
POOL = 60000


class TestIndirectSplit(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_list_values()
		seed_accounts(COMPANY)
		cls.made = centers.seed_centers(COMPANY)
		cls.accountant = make_user("sp.isp.accountant@example.com", ("accountant",))
		cls.official = frappe.db.get_value(
			"Account", {"company": COMPANY, "sp_account_kind": "Official", "is_group": 0}, order_by="name asc"
		)

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_setting(account_map=[], **{f"center_{key}": name for key, name in self.made.items()})
		ex.seed_account_map(COMPANY)
		isp.seed_account_map(COMPANY)

	def pool(self, amount, day=None):
		"""Indirect costs of the month (rent, salaries...): an expense on the Indirect center."""
		doc = frappe.get_doc(
			{
				"doctype": ex.EXPENSE,
				"company": COMPANY,
				"work_date": day or today(),
				"amount": amount,
				"expense_type": "Expense Type-OTHER",
				"center_type": "Indirect",
				"paid_from_kind": "Official account",
				"paid_from_account": self.official,
			}
		).insert()
		doc.submit()
		return doc

	def closed_station(self):
		quote = make_quotation(rate=1000, valid_days=3)
		quote.submit()
		frappe.db.set_value("SP Case", quote.sp_case, "accepted_quotation", quote.name)
		doc = frappe.get_doc({"doctype": STATION, "case": quote.sp_case, "company": COMPANY}).insert()
		frappe.db.set_value(STATION, doc.name, {"status": "Technically closed", "tech_closed_on": today()})
		return doc.name

	def split(self, lines, submit=True, month=None):
		doc = frappe.get_doc(
			{"doctype": isp.SPLIT, "company": COMPANY, "month": month or today(), "lines": lines}
		).insert()
		if submit:
			doc.submit()
		return doc

	def pool_center_net(self):
		(net,) = frappe.db.sql(
			"""select coalesce(sum(gle.debit - gle.credit), 0) from `tabGL Entry` gle
			join `tabAccount` acc on acc.name = gle.account
			where gle.cost_center = %s and gle.is_cancelled = 0 and acc.root_type = 'Expense'""",
			self.made["indirect"],
		)[0]
		return flt(net)

	def test_60000_shared_between_3_closed_stations_and_the_showroom(self):
		before = self.pool_center_net()
		self.pool(POOL)
		stations = [self.closed_station() for _share in SHARES]
		suggested = isp.suggest(COMPANY, today())
		self.assertTrue(set(stations) <= {line.get("station") for line in suggested["lines"]})
		self.assertIn({"target_type": "Showroom"}, suggested["lines"])
		pool = isp.pool_amount(COMPANY, today())
		extra = pool - POOL  # other indirect costs this month, if any, go to the showroom
		lines = [
			{"target_type": "Station", "station": s, "amount": a}
			for s, a in zip(stations, SHARES, strict=True)
		]
		lines.append({"target_type": "Showroom", "amount": SHOWROOM_SHARE + extra})
		doc = self.split(lines)
		self.assertTrue(doc.journal_entry)
		self.assertEqual(flt(self.pool_center_net() - before), -flt(pool - POOL))  # the pool nets 0
		for station, share in zip(stations, SHARES, strict=True):
			self.assertEqual(actual_cost(station)["indirect"], share)  # the Costs tab's indirect share

	def test_shares_that_do_not_add_up_to_the_pool_are_refused(self):
		self.pool(POOL)
		pool = isp.pool_amount(COMPANY, today())
		station = self.closed_station()
		with self.assertRaises(frappe.ValidationError):
			self.split(
				[
					{"target_type": "Station", "station": station, "amount": pool - 2000 - SHOWROOM_SHARE},
					{"target_type": "Showroom", "amount": SHOWROOM_SHARE},
				]
			)

	def test_a_share_as_a_percent_of_the_pool(self):
		last_month = add_months(today(), -1)  # this month is split by another test of the class
		self.pool(POOL, day=last_month)
		pool = isp.pool_amount(COMPANY, last_month)
		station = self.closed_station()
		doc = self.split(
			[
				{"target_type": "Station", "station": station, "pct": 25},
				{"target_type": "Showroom", "pct": 75},
			],
			submit=False,
			month=last_month,
		)
		self.assertEqual(flt(doc.lines[0].amount), flt(pool * 0.25, 2))
		self.assertEqual(abs(flt(doc.difference)) <= isp.TOLERANCE, True)

	def test_only_the_admin_splits(self):
		frappe.set_user(self.accountant)
		try:
			with self.assertRaises(frappe.PermissionError):
				self.split([{"target_type": "Showroom", "amount": 1}], submit=False)
		finally:
			frappe.set_user("Administrator")
