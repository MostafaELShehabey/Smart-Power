"""SP Station (SP-73): number, project, site warehouse, owners, workflow, money chips."""

import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate, today

from smart_power.sp_stations.money import next_due, refresh
from smart_power.sp_stations.station import record_write_off
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import (
	load_erpnext_test_data,
	make_quotation,
	make_user,
	set_setting,
)

load_erpnext_test_data()

COMPANY = "_Test Company"
WRITE_OFF_MAP = {
	"event": "Write-off",
	"debit_account": "_Test Write Off - _TC",
	"debit_center_rule": "Fixed",
	"debit_cost_center": "_Test Cost Center - _TC",
	"credit_account": "_Test Receivable - _TC",
	"credit_center_rule": "Fixed",
	"credit_cost_center": "_Test Cost Center - _TC",
	"project_rule": "Both sides",
}


def receive(station, amount, submit=True):
	"""A confirmed customer payment on the station (SP-114 makes these on confirmation)."""
	pe = frappe.get_doc(
		{
			"doctype": "Payment Entry",
			"payment_type": "Receive",
			"company": COMPANY,
			"party_type": "Customer",
			"party": station.customer,
			"paid_from": "_Test Receivable - _TC",
			"paid_to": "_Test Cash - _TC",
			"paid_amount": amount,
			"received_amount": amount,
			"reference_no": "SP73",
			"reference_date": today(),
			"project": station.project,
		}
	).insert()
	if submit:
		pe.submit()
	return pe


class TestStation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		set_setting(account_map=[WRITE_OFF_MAP])
		self.amira = make_user("sp.st.amira@example.com", ("project_manager",))
		self.quote = make_quotation(rate=200000, valid_days=3)
		self.quote.submit()
		frappe.db.set_value("SP Case", self.quote.sp_case, "accepted_quotation", self.quote.name)
		frappe.db.set_value("Customer", self.quote.party_name, "sp_featured", 0)

	def tearDown(self):
		frappe.set_user("Administrator")

	def station(self, **kw):
		frappe.set_user(self.amira)
		try:
			doc = frappe.get_doc(
				{"doctype": "SP Station", "case": self.quote.sp_case, "company": COMPANY, **kw}
			).insert()
		finally:
			frappe.set_user("Administrator")
		return frappe.get_doc("SP Station", doc.name)

	def test_opening_numbers_it_and_makes_its_project_and_site_warehouse(self):
		st = self.station()
		year = str(getdate(today()).year)
		self.assertRegex(st.name, rf"^{year}-\d{{3}}$")
		self.assertEqual(frappe.db.get_value("Project", st.project, "project_name"), st.name)
		self.assertEqual(frappe.db.get_value("Warehouse", st.site_warehouse, "sp_project"), st.project)
		self.assertTrue(st.site_warehouse.startswith(st.name))
		self.assertEqual(frappe.db.get_value("Customer", st.customer, "sp_featured"), 1)

	def test_it_takes_the_case_and_its_owners(self):
		st = self.station()
		case = frappe.get_doc("SP Case", self.quote.sp_case)
		self.assertEqual(
			(st.customer, st.quotation_accepted, st.sales_owner),
			(case.customer, self.quote.name, case.follow_up_owner),
		)
		self.assertEqual(st.customer_name, case.customer_name)  # found in the browser check
		self.assertEqual((st.execution_owner, st.collection_owner), (self.amira, self.amira))
		self.assertEqual(
			{r.role_kind for r in st.owner_history},
			{"Follow-up Owner", "Execution Owner", "Collection Owner"},
		)
		frappe.set_user(self.amira)
		st.collection_owner = "Administrator"
		with self.assertRaises(frappe.ValidationError):
			st.save()  # only the admin moves collection

	def test_money_chips_from_confirmed_payments_only(self):
		st = self.station()
		self.assertEqual(flt(st.agreed_amount), 200000)
		receive(st, 50000)
		receive(st, 30000, submit=False)  # not confirmed yet
		st.reload()
		self.assertEqual((flt(st.paid_amount), flt(st.remaining_amount)), (50000, 150000))

	def test_next_due_is_the_first_unpaid_instalment(self):
		d1, d2 = getdate(today()), getdate(add_days(today(), 30))
		schedule = [(d1, 100000), (d2, 100000)]
		self.assertEqual(next_due(schedule, 0), (d1, 100000))
		self.assertEqual(next_due(schedule, 50000), (d1, 50000))
		self.assertEqual(next_due(schedule, 120000), (d2, 80000))
		self.assertEqual(next_due(schedule, 200000), (None, 0.0))

	def test_financial_close_needs_nothing_remaining_or_a_write_off(self):
		st = self.station()
		receive(st, 150000)
		frappe.set_user(self.amira)
		for action in ("Start Purchasing", "Start Installing", "Close Technically"):
			st = apply_workflow(frappe.get_doc("SP Station", st.name), action)
		self.assertEqual(frappe.db.get_value("SP Station", st.name, "tech_closed_on"), getdate(today()))
		with self.assertRaises(frappe.ValidationError):
			apply_workflow(frappe.get_doc("SP Station", st.name), "Close Financially")
		with self.assertRaises(frappe.PermissionError):
			record_write_off(st.name, 50000, "عميل متعثر")
		frappe.set_user("Administrator")
		result = record_write_off(st.name, 50000, "عميل متعثر")
		self.assertEqual(flt(result["remaining_amount"]), 0)
		je = frappe.get_doc("Journal Entry", result["journal_entry"])
		self.assertEqual((je.sp_source_name, je.sp_posting_event), (st.name, "Write-off"))
		self.assertTrue(
			frappe.db.exists("SP Review Item", {"reference_name": st.name, "category": "Write-off"})
		)
		frappe.set_user(self.amira)
		st = apply_workflow(frappe.get_doc("SP Station", st.name), "Close Financially")
		self.assertEqual(st.status, "Financially closed")

	def test_cancel_only_by_the_admin_before_the_close(self):
		"""Cancel Station left the workflow for the admin's cancel, with its refunds (SP-176)."""
		from frappe.model.workflow import WorkflowTransitionError

		from smart_power.sp_stations.cancel import cancel_station

		st = self.station()
		frappe.set_user(self.amira)
		with self.assertRaises(WorkflowTransitionError):
			apply_workflow(frappe.get_doc("SP Station", st.name), "Cancel Station")
		frappe.set_user("Administrator")
		cancel_station(st.name, "العميل ألغى")
		self.assertEqual(frappe.db.get_value("SP Station", st.name, "status"), "Cancelled")
		closed = self.station()
		frappe.db.set_value("SP Station", closed.name, "status", "Technically closed")
		with self.assertRaises(frappe.ValidationError):
			cancel_station(closed.name, "متأخر")
