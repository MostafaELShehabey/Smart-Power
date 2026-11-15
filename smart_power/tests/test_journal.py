"""Journal (A6) and manual entry (A6b): reverse, never cancel (SP-119)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from smart_power.sp_finance.journal import reverse
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"


def manual_entry(debit=1000, credit=1000, submit=True):
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"company": COMPANY,
			"posting_date": today(),
			"user_remark": "فاتورة ضريبية خارج النظام",
			"accounts": [
				{
					"account": "_Test Account Cost for Goods Sold - _TC",
					"debit_in_account_currency": debit,
					"cost_center": "_Test Cost Center - _TC",
				},
				{
					"account": "_Test Bank - _TC",
					"credit_in_account_currency": credit,
					"cost_center": "_Test Cost Center - _TC",
				},
			],
		}
	)
	je.insert()
	if submit:
		je.submit()
	return je


class TestJournal(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_posted_entry_is_never_cancelled_and_reverse_links_to_it(self):
		je = manual_entry()
		with self.assertRaises(frappe.ValidationError):
			je.cancel()  # not even the Administrator
		je.reload()  # the refused cancel left the in-memory copy marked cancelled
		self.assertEqual(je.docstatus, 1)
		admin = make_user("sp.jn.admin@example.com", ("admin",), extra_roles=("Accounts Manager",))
		frappe.set_user(admin)
		self.assertFalse(frappe.has_permission("Journal Entry", "cancel", doc=je))
		reversal = frappe.get_doc("Journal Entry", reverse(je.name))
		frappe.set_user("Administrator")
		self.assertEqual((reversal.reversal_of, reversal.docstatus), (je.name, 0))
		lines = {
			(a.account, a.debit_in_account_currency, a.credit_in_account_currency) for a in reversal.accounts
		}
		self.assertIn(("_Test Bank - _TC", 1000, 0), lines)  # the sides swap
		self.assertEqual(reverse(je.name), reversal.name)  # once

	def test_a_manual_entry_is_flagged_and_listed_for_review(self):
		je = manual_entry()
		self.assertEqual(frappe.db.get_value("Journal Entry", je.name, "sp_is_manual"), 1)
		self.assertTrue(
			frappe.db.exists(
				"SP Review Item", {"reference_name": je.name, "category": "Manual Entry", "status": "Open"}
			)
		)

	def test_an_unbalanced_entry_is_never_posted(self):
		# a draft may be saved while it is being typed; it posts only when it balances
		draft = manual_entry(debit=1000, credit=900, submit=False)
		with self.assertRaises(frappe.ValidationError):
			draft.submit()

	def test_an_entry_from_a_document_goes_with_it(self):
		from smart_power.sp_finance.posting import cancel_postings, post
		from smart_power.tests.test_posting import COMPANY as POST_COMPANY
		from smart_power.tests.test_posting import winch_map
		from smart_power.tests.utils import make_test_case, set_setting

		set_setting(account_map=[winch_map()])
		source = frappe.get_doc("SP Case", make_test_case())
		name = post("Winch Internal Charge", source, 500, company=POST_COMPANY)
		self.assertEqual(frappe.db.get_value("Journal Entry", name, "sp_is_manual"), 0)
		with self.assertRaises(frappe.ValidationError):
			reverse(name)  # corrected through its source
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Journal Entry", name).cancel()
		cancel_postings(source)  # the source is cancelled: its entry goes with it
		self.assertEqual(frappe.db.get_value("Journal Entry", name, "docstatus"), 2)
