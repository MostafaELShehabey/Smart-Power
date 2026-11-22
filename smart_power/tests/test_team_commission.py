"""R5 Team commission (SP-143): the admin's monthly amounts post as an indirect cost owed to the
team, and each payment from an official account clears its part."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, get_first_day, get_last_day, getdate, today

from smart_power.sp_finance import month_close as mc
from smart_power.sp_finance import team_commission as tc
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import INDIRECT, seed_centers
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
MARCH = get_first_day(f"{getdate(today()).year}-03-01")
AMOUNTS = (4000, 3000, 3000, 2000)  # the story's 4 people, 12,000 in all


def balance(account, **filters):
	rows = frappe.get_all("GL Entry", {"account": account, "is_cancelled": 0, **filters}, ["debit", "credit"])
	return sum(flt(r.debit) - flt(r.credit) for r in rows)


class TestTeamCommission(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)
		cls.centers = seed_centers(COMPANY)
		cls.manager = make_user("sp.tc.manager@example.com", ("commission_manager",))
		cls.people = [make_user(f"sp.tc.person{i}@example.com", ("quote_creator",)) for i in range(4)]
		cls.bank = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_name": "Smart Power Bank Misr"}
		)
		cls.payable = tc._account(COMPANY, tc.PAYABLE_ACCOUNT)
		cls.expense = tc._account(COMPANY, tc.EXPENSE_ACCOUNT)

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		set_setting(account_map=[], **{f"center_{k}": v for k, v in self.centers.items()})
		tc.seed_account_map(COMPANY)

	def sheet(self, month=MARCH, amounts=AMOUNTS):
		frappe.set_user(self.manager)
		doc = frappe.get_doc(
			{
				"doctype": tc.DOCTYPE,
				"company": COMPANY,
				"month": month,
				"lines": [{"user": u, "amount": a} for u, a in zip(self.people, amounts, strict=False)],
			}
		).insert()
		frappe.set_user("Administrator")
		return doc

	def pay(self, doc, idx):
		frappe.set_user(self.manager)
		entry = tc.mark_paid(doc.name, doc.lines[idx].name, self.bank)
		frappe.set_user("Administrator")
		doc.reload()
		return entry

	def test_march_for_4_people_owes_12000_and_paying_2_reduces_it(self):
		before_payable, before_bank = balance(self.payable), balance(self.bank)
		doc = self.sheet()
		self.assertEqual(balance(self.payable) - before_payable, -12000)  # commission payable 12,000
		entry = frappe.get_doc("Journal Entry", doc.accrual_entry)
		self.assertEqual(getdate(entry.posting_date), get_last_day(MARCH))
		self.assertEqual({r.cost_center for r in entry.accounts}, {self.centers[INDIRECT]})
		self.pay(doc, 0)
		self.pay(doc, 1)
		self.assertEqual(balance(self.payable) - before_payable, -5000)  # 4,000 and 3,000 paid
		self.assertEqual(balance(self.bank) - before_bank, -7000)
		self.assertEqual((doc.paid_total, doc.payable), (7000, 5000))
		self.assertEqual((doc.lines[0].paid, doc.lines[0].paid_from_account), (1, self.bank))

	def test_a_new_amount_replaces_the_entry(self):
		doc = self.sheet(month=get_first_day(f"{getdate(today()).year}-04-01"))
		first = doc.accrual_entry
		doc.lines[3].amount = 3000
		doc.save()
		self.assertEqual(frappe.db.get_value("Journal Entry", first, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Journal Entry", doc.accrual_entry, "total_debit"), 13000)

	def test_a_paid_line_is_locked(self):
		doc = self.sheet(month=get_first_day(f"{getdate(today()).year}-05-01"))
		self.pay(doc, 0)
		doc.lines[0].amount = 1
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.lines[1].paid = 1  # only Mark Paid marks it, so its payment posts
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		with self.assertRaises(frappe.ValidationError):
			doc.delete()

	def test_only_an_official_account_pays(self):
		doc = self.sheet(month=get_first_day(f"{getdate(today()).year}-06-01"))
		with self.assertRaises(frappe.ValidationError):
			tc.mark_paid(doc.name, doc.lines[0].name, self.expense)

	def test_one_sheet_per_month(self):
		month = get_first_day(f"{getdate(today()).year}-07-01")
		self.sheet(month=month)
		with self.assertRaises(frappe.ValidationError):
			self.sheet(month=month)

	def test_the_month_close_r5_row_follows_the_sheet(self):
		month = get_first_day(f"{getdate(today()).year}-08-01")
		end = get_last_day(month)
		self.assertEqual(mc.check_commission(COMPANY, month, end)["status"], mc.RED)
		self.sheet(month=month)
		self.assertEqual(mc.check_commission(COMPANY, month, end)["status"], mc.GREEN)
