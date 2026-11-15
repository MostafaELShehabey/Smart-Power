"""Customer advances, Agri Bank A8 (SP-121)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_finance import advances
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.balances import advances as station_advances
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_station import COMPANY
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

BANK = "_Test SP Agri Bank"


def balance(account, project=None):
	filters = {"account": account, "is_cancelled": 0}
	if project:
		filters["project"] = project
	rows = frappe.get_all("GL Entry", filters, ["debit", "credit"])
	return sum(flt(r.debit) - flt(r.credit) for r in rows)


class TestAdvances(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		if not frappe.db.exists("Bank", BANK):
			frappe.get_doc({"doctype": "Bank", "bank_name": BANK}).insert()

	def setUp(self):
		set_setting(account_map=[])
		advances.seed_account_map(COMPANY)
		self.banker = make_user("sp.adv.banker@example.com", ("bank_financing",))
		self.pm = make_user("sp.adv.pm@example.com", ("project_manager",))
		acc = lambda n: frappe.db.get_value("Account", {"company": COMPANY, "account_name": n})  # noqa: E731
		self.bank, self.post = acc("Smart Power Bank Misr"), acc("The Post")
		self.advances_account, self.fees = acc("Customer Advances - Agri Bank"), acc("Advance Fees")
		self.station = self.make_station()

	def tearDown(self):
		frappe.set_user("Administrator")

	def make_station(self):
		quote = make_quotation(rate=200000, valid_days=3)
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

	def advance(self, amount=20000, paid_from=None, submit=True):
		frappe.set_user(self.banker)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SP Customer Advance",
					"station": self.station.name,
					"bank": BANK,
					"branch": "المنيا",
					"amount": amount,
					"paid_on": today(),
					"paid_from_account": paid_from or self.bank,
				}
			).insert()
			if submit:
				doc.submit()
			return frappe.get_doc("SP Customer Advance", doc.name)
		finally:
			frappe.set_user("Administrator")

	def repay(self, doc, amount, fee=0):
		frappe.set_user(self.banker)
		try:
			return advances.add_repayment(
				doc.name, self.bank, amount=amount, fee_amount=fee, reference="REL-1"
			)
		finally:
			frappe.set_user("Administrator")

	def test_a_20000_advance_is_on_the_advances_account_and_the_remaining_is_unchanged(self):
		remaining = flt(self.station.remaining_amount)
		bank_before = balance(self.bank)
		doc = self.advance(20000)
		self.assertEqual(doc.status, "Open")
		self.assertEqual(balance(self.advances_account, self.station.project), 20000)
		self.assertEqual(balance(self.bank), bank_before - 20000)
		self.station.reload()
		self.assertEqual(flt(self.station.remaining_amount), remaining)
		self.assertEqual(station_advances(self.station), 20000)  # AR1 shows it

	def test_the_bank_releases_20000_with_a_500_fee(self):
		fees_before = balance(self.fees)
		doc = self.advance(20000)
		result = self.repay(doc, 20000, fee=500)
		self.assertEqual(result["status"], "Repaid")
		doc.reload()
		self.assertEqual(
			(flt(doc.repaid_amount), flt(doc.fee_amount), flt(doc.outstanding_amount)), (20000, 500, 0)
		)
		self.assertEqual(balance(self.fees) - fees_before, -500)  # income: a credit of 500
		self.assertEqual(balance(self.advances_account, self.station.project), 0)
		self.assertTrue(doc.repayments[0].journal_entry and doc.repayments[0].fee_entry)

	def test_partly_repaid_then_unpaid_then_repaid(self):
		doc = self.advance(20000)
		self.assertEqual(self.repay(doc, 5000)["status"], "Partly repaid")
		with self.assertRaises(frappe.ValidationError):
			self.repay(doc, 16000)  # more than is outstanding
		frappe.set_user(self.banker)
		with self.assertRaises(frappe.MandatoryError):
			advances.add_repayment(doc.name, "", amount=1000)  # never the map's account by default
		frappe.set_user("Administrator")
		frappe.set_user(self.banker)
		self.assertEqual(advances.mark_unpaid(doc.name, "البنك لم يصرف"), "Unpaid - overdue")
		frappe.set_user("Administrator")
		self.assertEqual(self.repay(doc, 5000)["status"], "Unpaid - overdue")
		self.assertEqual(self.repay(doc, 10000)["status"], "Repaid")
		self.assertIn("البنك لم يصرف", frappe.db.get_value("SP Customer Advance", doc.name, "note"))

	def test_paid_from_an_official_account_only(self):
		cash = frappe.db.get_value("Account", {"company": COMPANY, "account_type": "Cash", "is_group": 0})
		frappe.db.set_value("Account", cash, "sp_account_kind", "Transit")
		with self.assertRaises(frappe.ValidationError):
			self.advance(paid_from=cash, submit=False)

	def test_only_the_admin_or_bank_financing_repays(self):
		doc = self.advance(20000)
		frappe.set_user(self.pm)
		with self.assertRaises(frappe.PermissionError):
			advances.add_repayment(doc.name, self.bank, amount=1000)

	def test_an_agri_bank_contract_tasks_the_admin_until_the_advance_is_recorded(self):
		so = frappe._dict(
			sp_financing_type=advances.AGRI_BANK, sp_station=self.station.name, customer_name="عميل"
		)
		advances.on_contract(so)
		task = {
			"reference_doctype": "SP Station",
			"reference_name": self.station.name,
			"task_type": advances.TASK_TYPE,
		}
		self.assertTrue(frappe.db.exists("SP Task", {**task, "assigned_to": self.banker, "status": "Open"}))
		self.advance(20000)
		self.assertFalse(frappe.db.exists("SP Task", {**task, "status": "Open"}))
		advances.on_contract(so)  # recorded already: no new task
		self.assertFalse(frappe.db.exists("SP Task", {**task, "status": "Open"}))
		advances.on_contract(frappe._dict(so, sp_financing_type="Financing Type-CASH"))
		self.assertFalse(frappe.db.exists("SP Task", {**task, "status": "Open"}))

	def test_cancelling_the_advance_cancels_its_entries(self):
		doc = self.advance(20000)
		self.repay(doc, 5000, fee=100)
		doc.reload()
		doc.cancel()
		self.assertEqual(balance(self.advances_account, self.station.project), 0)
		self.assertFalse(
			frappe.db.exists(
				"Journal Entry",
				{"sp_source_doctype": "SP Customer Advance", "sp_source_name": doc.name, "docstatus": 1},
			)
		)
		self.assertEqual(frappe.db.get_value("SP Customer Advance", doc.name, "status"), "Cancelled")

	def test_the_contracts_financing_reaches_its_station(self):
		from smart_power.sp_stations.contract import validate_order

		so = frappe._dict(
			sp_case="CS-X",
			sp_station=self.station.name,
			sp_financing_type=advances.AGRI_BANK,
			sp_bank_branch="المنيا",
			name="SO-X",
			is_new=lambda: False,
		)
		validate_order(so)  # a saved contract whose financing changed
		self.assertEqual(
			frappe.db.get_value("SP Station", self.station.name, ["financing_type", "bank_branch"]),
			(advances.AGRI_BANK, "المنيا"),
		)
