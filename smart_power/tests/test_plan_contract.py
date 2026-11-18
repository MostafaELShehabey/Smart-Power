"""The chosen installment plan becomes the contract's terms (SP-60): its price over the cash price
as a finance line, its schedule, and one postal cheque row per installment at the cheque value;
a cheque joins the register when its number is filled in."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_quotes import payment_plans as pp
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
PLAN = "SP60 contract plan"


class TestPlanContract(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		set_setting(cost_of_money_pct=20)
		frappe.db.set_value(pp.TEMPLATE, {"name": ("!=", PLAN)}, "is_active", 0)
		if not frappe.db.exists(pp.TEMPLATE, PLAN):
			frappe.get_doc(
				{
					"doctype": pp.TEMPLATE,
					"plan_name": PLAN,
					"is_active": 1,
					"months": 12,
					"every_months": 3,
					"down_payment_pct": 25,
					"finance_service_pct": 10,
					"service_basis": pp.YEARLY,
					"cheque_uplift_type": pp.PERCENT,
					"cheque_uplift": 5,
				}
			).insert()
		self.amira = make_user("sp.pc.amira@example.com", ("project_manager", "contract_manager"))

	def quote(self, choose=True):
		q = make_quotation(rate=100000, valid_days=3)
		q.submit()
		q.reload()
		if choose:
			q.sp_payment_plan = PLAN
			q.save()
		approve_version(q.name)
		return frappe.get_doc("Quotation", q.name)

	def contract(self, q):
		frappe.set_user(self.amira)
		try:
			return frappe.get_doc("Sales Order", make_contract(q.sp_case)["sales_order"])
		finally:
			frappe.set_user("Administrator")

	def test_the_plan_becomes_the_contract(self):
		q = self.quote()
		plan = next(r for r in q.sp_payment_plans if r.template == PLAN)
		# 100,000 cash, 25,000 down, 75,000 financed + 10% x 1 year = 107,500 in 4 quarterly installments
		self.assertEqual((plan.plan_total, plan.down_payment, plan.installments), (107500, 25000, 4))
		so = self.contract(q)
		finance = [r for r in so.items if r.item_code == "SP-FINANCE"]
		self.assertEqual(len(finance), 1)
		self.assertEqual(flt(finance[0].amount), 7500)
		self.assertEqual(flt(so.rounded_total or so.grand_total), 107500)
		amounts = [flt(r.payment_amount) for r in so.payment_schedule]
		self.assertEqual(amounts, [25000, 20625, 20625, 20625, 20625])
		self.assertEqual(flt(sum(amounts), 2), 107500)
		self.assertEqual([flt(r.amount) for r in so.sp_cheques], [21656.25] * 4)  # installment + 5%
		self.assertTrue(all(not r.cheque_no for r in so.sp_cheques))

	def test_a_cheque_joins_the_register_when_its_number_comes(self):
		so = self.contract(self.quote())
		so.submit()
		self.assertFalse(frappe.db.exists("SP Cheque", {"sales_order": so.name}))
		so.reload()
		so.sp_cheques[0].cheque_no = "PC-0001"
		so.sp_cheques[0].bank = "The Post"
		so.save()
		cheque = frappe.get_all("SP Cheque", {"sales_order": so.name}, ["cheque_no", "amount", "due_date"])
		self.assertEqual([(c.cheque_no, flt(c.amount)) for c in cheque], [("PC-0001", 21656.25)])
		self.assertEqual(str(cheque[0].due_date), str(so.sp_cheques[0].due_date))

	def test_cash_keeps_the_quote_terms(self):
		so = self.contract(self.quote(choose=False))
		self.assertFalse([r for r in so.items if r.item_code == "SP-FINANCE"])
		self.assertFalse(so.sp_cheques)
		self.assertEqual(flt(so.rounded_total or so.grand_total), 100000)
