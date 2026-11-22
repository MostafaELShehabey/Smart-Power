"""R2 Cash flow (SP-140): the official balances, plus what is coming in, minus what suppliers are
owed, bucket by bucket. The class shares one transaction, so every check reads deltas."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate, today

from smart_power.sp_finance import cash_flow as cf
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_purchase_orders import COMPANY, station
from smart_power.tests.test_supplier_ledger import invoice
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()

OPENING, DUE, DUES = 100000, 60000, 80000  # the story's example
CHEQUE = 20000
SOON, LATER, LATE = 3, 10, -5  # days from today: week 1, week 2, overdue


class TestCashFlow(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		cls.bank = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_name": "Smart Power Bank Misr"}
		)
		cls.vendor = (
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": "SP140 Supplier",
					"supplier_group": "_Test Supplier Group",
				}
			)
			.insert()
			.name
		)

	def weeks(self, **filters):
		return {r["period"]: r for r in cf.rows({"company": COMPANY, **filters})}

	def deposit(self, amount):
		doc = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COMPANY,
				"posting_date": today(),
				"accounts": [
					{"account": self.bank, "debit_in_account_currency": amount},
					{"account": "_Test Bank - _TC", "credit_in_account_currency": amount},
				],
			}
		).insert()
		doc.submit()

	def station_due(self, amount, days):
		"""A contracted station whose one instalment is due in `days`."""
		st = station()
		row = frappe.db.get_value("Payment Schedule", {"parent": st.sales_order}, "name")
		frappe.db.set_value(
			"Payment Schedule", row, {"payment_amount": amount, "due_date": add_days(today(), days)}
		)
		return st

	def cheque(self, st, amount, days):
		return frappe.get_doc(
			{
				"doctype": "SP Cheque",
				"cheque_no": frappe.generate_hash(length=8),
				"amount": amount,
				"due_date": add_days(today(), days),
				"bank_or_post": "SP140 post office",
				"holder": "Administrator",
				"station": st.name,
			}
		).insert()

	def delta(self, before, after, period, field):
		return flt(after[period][field]) - flt(before[period][field])

	def test_100000_opening_60000_due_and_80000_owed_close_week_1_at_80000(self):
		before = self.weeks()
		self.deposit(OPENING)
		self.station_due(DUE, SOON)
		invoice([(None, DUES)], self.vendor, due_days=SOON)
		after = self.weeks()
		week = _("Week {0}").format(1)
		self.assertEqual(self.delta(before, after, week, "opening"), OPENING)
		self.assertEqual(self.delta(before, after, week, "installments"), DUE)
		self.assertEqual(self.delta(before, after, week, "supplier_dues"), DUES)
		self.assertEqual(self.delta(before, after, week, "closing"), OPENING + DUE - DUES)  # 80,000
		self.assertEqual(self.delta(before, after, _("Week {0}").format(2), "opening"), OPENING + DUE - DUES)

	def test_an_open_cheque_replaces_the_instalment_it_pays(self):
		before = self.weeks()
		st = self.station_due(DUE, SOON)
		self.cheque(st, CHEQUE, LATER)
		after = self.weeks()
		self.assertEqual(self.delta(before, after, _("Week {0}").format(1), "installments"), DUE - CHEQUE)
		self.assertEqual(self.delta(before, after, _("Week {0}").format(2), "cheques"), CHEQUE)
		total = sum(self.delta(before, after, p, "inflow") for p in after if p != _("Overdue"))
		self.assertEqual(total, DUE)  # counted once

	def test_overdue_money_is_shown_but_not_counted(self):
		before = self.weeks()
		self.station_due(DUE, LATE)
		after = self.weeks()
		self.assertEqual(self.delta(before, after, _("Overdue"), "installments"), DUE)
		self.assertIsNone(after[_("Overdue")]["closing"])
		last = _("Week {0}").format(len(after) - 1)
		self.assertEqual(self.delta(before, after, last, "closing"), 0)

	def test_weeks_and_months_and_the_horizon_limits(self):
		self.assertEqual(
			len(cf.rows({"company": COMPANY, "horizon": 99})), 26 + 1
		)  # sp-allow-number: max + overdue
		months = cf.rows({"company": COMPANY, "granularity": "Month", "horizon": 3})
		self.assertEqual(len(months), 3 + 1)  # sp-allow-number: 3 months + overdue
		self.assertEqual(getdate(months[1]["from_date"]), getdate(today()))
		self.assertEqual(getdate(months[2]["from_date"]).day, 1)

	def test_the_transit_balance_counts_only_when_asked(self):
		from smart_power.sp_finance.accounts import holder_account

		transit = holder_account("Administrator", "Transit", COMPANY)
		before = cf.opening(COMPANY, today()), cf.opening(COMPANY, today(), include_transit=True)
		doc = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": COMPANY,
				"posting_date": today(),
				"accounts": [
					{"account": transit, "debit_in_account_currency": CHEQUE},
					{"account": "_Test Bank - _TC", "credit_in_account_currency": CHEQUE},
				],
			}
		).insert()
		doc.submit()
		self.assertEqual(cf.opening(COMPANY, today()) - before[0], 0)
		self.assertEqual(cf.opening(COMPANY, today(), include_transit=True) - before[1], CHEQUE)


def _(text):
	return frappe._(text)
