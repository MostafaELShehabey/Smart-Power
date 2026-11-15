"""Custody A9 (SP-122): give, record expenses, settle, approve; reject; return or carry."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_finance import centers, custody
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.confirmations import pending
from smart_power.sp_finance.confirmations import preview as a1_preview
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import ensure_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
PHOTO = "/files/receipt.jpg"


def balance(account, **filters):
	rows = frappe.get_all("GL Entry", {"account": account, "is_cancelled": 0, **filters}, ["debit", "credit"])
	return sum(flt(r.debit) - flt(r.credit) for r in rows)


class TestCustody(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)

	def setUp(self):
		made = centers.seed_centers(COMPANY)
		set_setting(**{f"center_{k}": v for k, v in made.items()})
		self.projects, self.indirect = made[centers.PROJECTS], made[centers.INDIRECT]
		self.admin = make_user("sp.cu.admin@example.com", ("admin",))
		self.mostafa = make_user("sp.cu.mostafa@example.com", ("custody_holder",))
		self.aya = make_user("sp.cu.aya@example.com", ("custody_holder",))
		acc = lambda n: frappe.db.get_value("Account", {"company": COMPANY, "account_name": n})  # noqa: E731
		self.bank, self.petty = acc("Smart Power Bank Misr"), acc("Petty Cash Expenses")
		self.travel = acc("Travel Expenses")
		self.station = self.make_station()
		self.doc = self.give(self.mostafa, 5000)
		# each test starts from an empty custody account (tests share a transaction)
		self.start = balance(self.doc.custody_account) - 5000

	def tearDown(self):
		frappe.set_user("Administrator")

	def make_station(self):
		q = make_quotation(rate=50000, valid_days=3, save=False)
		q.insert()
		q.set(
			"payment_schedule",
			[{"due_date": add_days(today(), 30), "invoice_portion": 100, "payment_amount": 50000}],
		)
		q.save()
		q.submit()
		approve_version(q.name)
		return frappe.get_doc("SP Station", ensure_contract(q.sp_case)["station"])

	def give(self, holder, amount):
		frappe.set_user(self.admin)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "SP Custody",
					"holder": holder,
					"company": COMPANY,
					"amount": amount,
					"from_account": self.bank,
				}
			).insert()
			doc.submit()
			return frappe.get_doc("SP Custody", doc.name)
		finally:
			frappe.set_user("Administrator")

	def expense(self, amount, code, on, user=None, **kw):
		frappe.set_user(user or self.mostafa)
		try:
			return custody.add_expense(
				self.doc.name,
				{
					"amount": amount,
					"expense_type": f"Expense Type-{code}",
					"center_type": on,
					"receipt_photo": PHOTO,
					"work_date": today(),
					**kw,
				},
			)
		finally:
			frappe.set_user("Administrator")

	def three_expenses(self):
		self.expense(400, "FUEL", "Station", station=self.station.name)
		self.expense(250, "TOOLS", "Petty cash", cost_center=self.projects)
		self.expense(150, "FOOD", "Center", cost_center=self.indirect)

	def settle(self, **kw):
		frappe.set_user(self.mostafa)
		try:
			return frappe.get_doc("SP Custody Settlement", custody.submit_settlement(self.doc.name, **kw))
		finally:
			frappe.set_user("Administrator")

	def approve(self, settlement):
		frappe.set_user(self.admin)
		try:
			return custody.confirm(settlement.name)
		finally:
			frappe.set_user("Administrator")

	def test_three_expenses_land_on_station_petty_cash_and_indirect_pool(self):
		self.three_expenses()
		food = frappe.db.get_value("Account", {"company": COMPANY, "account_name": "Entertainment Expenses"})
		petty_before = balance(self.petty)
		food_before = balance(food, cost_center=self.indirect)
		indirect_before = balance(self.travel, cost_center=self.indirect)
		settlement = self.settle()
		self.assertEqual((settlement.status, flt(settlement.total)), ("Pending", 800))
		self.assertEqual(frappe.db.get_value("SP Custody", self.doc.name, "status"), "Settlement submitted")
		frappe.set_user(self.admin)
		self.assertIn(settlement.name, [i["name"] for i in pending()["items"]])  # in A1
		lines = a1_preview("SP Custody Settlement", settlement.name)
		self.assertEqual(sum(r["debit"] for r in lines), sum(r["credit"] for r in lines))
		frappe.set_user("Administrator")
		self.approve(settlement)
		project = self.station.project
		self.assertEqual(
			balance(self.travel, project=project, cost_center=self.projects), 400
		)  # the station +400
		self.assertEqual(balance(self.petty) - petty_before, 250)  # petty cash +250
		self.assertEqual(
			balance(food, cost_center=self.indirect) - food_before, 150
		)  # the indirect pool +150
		self.assertEqual(balance(self.travel, cost_center=self.indirect), indirect_before)
		self.assertEqual(balance(self.doc.custody_account) - self.start, 4200)
		doc = frappe.get_doc("SP Custody", self.doc.name)
		self.assertEqual((doc.status, flt(doc.approved_amount)), ("Carried", 800))
		self.assertEqual({r.status for r in doc.lines}, {"Approved"})

	def test_a_rejected_expense_returns_with_the_reason_and_the_rest_are_approved(self):
		self.three_expenses()
		settlement = self.settle()
		settlement.lines[2].decision = "Reject"
		settlement.lines[2].reject_reason = "بدون فاتورة"
		settlement.flags.ignore_permissions = True
		settlement.save()
		self.approve(settlement)
		doc = frappe.get_doc("SP Custody", self.doc.name)
		self.assertEqual([r.status for r in doc.lines], ["Approved", "Approved", "Rejected"])
		self.assertEqual(doc.lines[2].reject_reason, "بدون فاتورة")
		self.assertEqual(doc.status, "Spending")  # back with the holder
		self.assertEqual(balance(self.doc.custody_account) - self.start, 4350)
		self.assertTrue(
			frappe.db.exists(
				"SP Task", {"assigned_to": self.mostafa, "reference_name": self.doc.name, "status": "Open"}
			)
		)
		again = self.settle()  # the rejected expense can be settled again
		self.assertEqual([r.amount for r in again.lines], [150])

	def test_return_leftover_settles_the_balance_to_zero(self):
		self.three_expenses()
		bank_before = balance(self.bank)
		self.approve(self.settle(leftover_action="Return", return_to_account=self.bank))
		self.assertEqual(balance(self.doc.custody_account), 0)
		self.assertEqual(balance(self.bank) - bank_before, 4200 + self.start)
		self.assertEqual(frappe.db.get_value("SP Custody", self.doc.name, "status"), "Returned")

	def test_the_whole_settlement_rejected_posts_nothing(self):
		self.three_expenses()
		settlement = self.settle()
		frappe.set_user(self.admin)
		custody.reject(settlement.name, "الصور غير واضحة")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("SP Custody Settlement", settlement.name, "status"), "Rejected")
		self.assertEqual(balance(self.doc.custody_account) - self.start, 5000)
		doc = frappe.get_doc("SP Custody", self.doc.name)
		self.assertEqual(({r.status for r in doc.lines}, doc.status), ({"Rejected"}, "Spending"))

	def test_a_holder_sees_and_records_only_their_own_custody(self):
		frappe.set_user(self.aya)
		self.assertNotIn(self.doc.name, frappe.get_list("SP Custody", pluck="name"))
		with self.assertRaises(frappe.PermissionError):
			custody.add_expense(
				self.doc.name,
				{
					"amount": 10,
					"expense_type": "Expense Type-FOOD",
					"center_type": "Center",
					"cost_center": self.indirect,
				},
			)
		with self.assertRaises(frappe.PermissionError):
			custody.my_custody(self.mostafa)
		frappe.set_user(self.mostafa)
		self.assertIn(self.doc.name, frappe.get_list("SP Custody", pluck="name"))
		mine = custody.my_custody()
		self.assertEqual(mine["balance"] - self.start, 5000)
		self.assertIn(self.doc.name, [c["name"] for c in mine["custodies"]])

	def test_the_same_mobile_entry_is_saved_once(self):
		first = self.expense(100, "TRANSPORT", "Center", cost_center=self.indirect, client_uuid="m11-abc")
		second = self.expense(100, "TRANSPORT", "Center", cost_center=self.indirect, client_uuid="m11-abc")
		self.assertEqual(first, second)
		self.assertEqual(len(frappe.get_doc("SP Custody", self.doc.name).lines), 1)

	def test_only_the_admin_gives_custody_from_an_official_account(self):
		frappe.set_user(self.mostafa)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "SP Custody",
					"holder": self.mostafa,
					"company": COMPANY,
					"amount": 100,
					"from_account": self.bank,
				}
			).insert()
		frappe.set_user(self.admin)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "SP Custody",
					"holder": self.mostafa,
					"company": COMPANY,
					"amount": 100,
					"from_account": self.petty,
				}
			).insert()
