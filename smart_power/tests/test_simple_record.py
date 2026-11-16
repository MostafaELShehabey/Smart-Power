"""G7 Simple record (SP-43): one step, a simple entry when money moved, edited with a reason."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_core.setup.seed import seed_list_values
from smart_power.sp_finance import centers, simple_record
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
STORAGE_FEE = "Simple Record Type-STORAGE_FEE"


def account(name: str) -> str:
	return frappe.db.get_value("Account", {"company": COMPANY, "account_name": name, "is_group": 0})


class SimpleRecordCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_list_values()
		seed_accounts(COMPANY)

	def setUp(self):
		self.centers = centers.seed_centers(COMPANY)
		set_setting(**{f"center_{k}": v for k, v in self.centers.items()})
		simple_record.seed_account_map(COMPANY)
		self.accountant = make_user("sp.sr.accountant@example.com", ("accountant",))
		self.bank = account("Smart Power Bank Misr")
		self.showroom = self.centers[centers.SHOWROOM]

	def tearDown(self):
		frappe.set_user("Administrator")

	def record(self, amount=1500, **kw):
		frappe.set_user(self.accountant)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SP Simple Record",
					"company": COMPANY,
					"work_date": today(),
					"record_type": STORAGE_FEE,
					"amount": amount,
					"direction": "Money In",
					"account": self.bank,
					"cost_center": self.showroom,
					"note": "رسوم تخزين حاوية",
					**kw,
				}
			).insert()
			doc.submit()
			return doc
		finally:
			frappe.set_user("Administrator")

	def entry_lines(self, je: str) -> dict:
		return {
			r.account: (flt(r.debit), flt(r.credit), r.cost_center)
			for r in frappe.get_all(
				"Journal Entry Account", {"parent": je}, ["account", "debit", "credit", "cost_center"]
			)
		}


class TestSimpleRecord(SimpleRecordCase):
	def test_a_storage_fee_posts_dr_bank_cr_storage_fee_income_on_the_showroom(self):
		doc = self.record()
		self.assertTrue(doc.journal_entry)
		self.assertEqual(frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus"), 1)
		self.assertEqual(
			self.entry_lines(doc.journal_entry),
			{
				self.bank: (1500, 0, self.showroom),
				account("Storage Fee Income"): (0, 1500, self.showroom),
			},
		)
		self.assertTrue(doc.entry_time)

	def test_an_expense_goes_out_and_a_note_posts_nothing(self):
		out = self.record(300, record_type="Simple Record Type-OTHER_EXPENSE", direction="Money Out")
		lines = self.entry_lines(out.journal_entry)
		self.assertEqual(lines[self.bank][:2], (0, 300))
		self.assertEqual(lines[account("Miscellaneous Expenses")][:2], (300, 0))
		note = self.record(0, direction="None", account=None)
		self.assertFalse(note.journal_entry)

	def test_only_the_admin_and_the_accountant_record(self):
		clerk = make_user("sp.sr.clerk@example.com", ("lead_intake",))
		self.assertFalse(frappe.has_permission("SP Simple Record", "create", user=clerk))
		self.assertTrue(frappe.has_permission("SP Simple Record", "create", user=self.accountant))
