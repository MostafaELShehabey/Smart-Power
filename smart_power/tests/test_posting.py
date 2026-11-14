"""Posting service with the Account Map (SP-113)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_finance.posting import cancel_postings, post, postings, preview
from smart_power.tests.utils import load_erpnext_test_data, make_test_case, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
INCOME, COST = "Sales - _TC", "_Test Account Cost for Goods Sold - _TC"
WINCH_CENTER, PROJECTS_CENTER = "_Test Cost Center - _TC", "_Test Cost Center 2 - _TC"


def winch_map(cost_account=COST):
	# a winch job on a station: the station's cost (Projects center, its project) against
	# winch income (Winch center)
	return {
		"event": "Winch Internal Charge",
		"debit_account": cost_account,
		"debit_center_rule": "Fixed",
		"debit_cost_center": PROJECTS_CENTER,
		"credit_account": INCOME,
		"credit_center_rule": "Fixed",
		"credit_cost_center": WINCH_CENTER,
		"project_rule": "Debit side",
	}


class TestPosting(IntegrationTestCase):
	def setUp(self):
		set_setting(account_map=[winch_map()])
		self.project = (
			frappe.db.get_value("Project", {"project_name": "SP-113 2027-014"})
			or frappe.get_doc({"doctype": "Project", "project_name": "SP-113 2027-014", "company": COMPANY})
			.insert()
			.name
		)
		self.source = frappe.get_doc("SP Case", make_test_case())  # stands in for the winch job

	def je(self, name):
		return frappe.get_doc("Journal Entry", name)

	def test_winch_job_posts_one_balanced_entry_on_two_centers(self):
		name = post("Winch Internal Charge", self.source, 1500, company=COMPANY, project=self.project)
		entry = self.je(name)
		self.assertEqual(entry.docstatus, 1)
		by_account = {a.account: a for a in entry.accounts}
		self.assertEqual(
			(by_account[COST].cost_center, by_account[COST].project, flt(by_account[COST].debit)),
			(PROJECTS_CENTER, self.project, 1500),
		)
		self.assertEqual(
			(by_account[INCOME].cost_center, by_account[INCOME].project, flt(by_account[INCOME].credit)),
			(WINCH_CENTER, None, 1500),
		)
		self.assertEqual(flt(entry.total_debit), flt(entry.total_credit))
		self.assertEqual(
			(entry.sp_posting_event, entry.sp_source_doctype, entry.sp_source_name),
			("Winch Internal Charge", "SP Case", self.source.name),
		)

	def test_a_map_change_applies_to_the_next_posting_only(self):
		first = post("Winch Internal Charge", self.source, 100, company=COMPANY, project=self.project)
		other = "_Test Account Excise Duty - _TC"
		set_setting(account_map=[winch_map(cost_account=other)])
		second = post("Winch Internal Charge", self.source, 100, company=COMPANY, project=self.project)
		self.assertIn(COST, [a.account for a in self.je(first).accounts])  # untouched
		self.assertIn(other, [a.account for a in self.je(second).accounts])

	def test_preview_saves_nothing(self):
		before = frappe.db.count("Journal Entry")
		lines = preview("Winch Internal Charge", self.source, 700, company=COMPANY, project=self.project)
		self.assertEqual([(line["debit"], line["credit"]) for line in lines], [(700, 0), (0, 700)])
		self.assertEqual(frappe.db.count("Journal Entry"), before)

	def test_cancelling_the_source_cancels_its_entries(self):
		name = post("Winch Internal Charge", self.source, 300, company=COMPANY, project=self.project)
		self.assertEqual(postings(self.source), [name])
		cancel_postings(self.source)
		self.assertEqual(self.je(name).docstatus, 2)
		self.assertIn(
			"smart_power.sp_finance.posting.cancel_postings", frappe.get_hooks("doc_events")["*"]["on_cancel"]
		)

	def test_center_from_the_document(self):
		row = winch_map()
		row["debit_center_rule"] = "From document"
		set_setting(account_map=[row])
		name = post("Winch Internal Charge", self.source, 50, company=COMPANY, cost_center=WINCH_CENTER)
		self.assertEqual({a.cost_center for a in self.je(name).accounts}, {WINCH_CENTER})

	def test_unmapped_event_and_bad_amount_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			post("Cheque Bounce", self.source, 100, company=COMPANY)
		with self.assertRaises(frappe.ValidationError):
			post("Winch Internal Charge", self.source, 0, company=COMPANY)
