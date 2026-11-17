"""Installment plans (SP-60): the template's terms and flags price each plan; the company's
contribution and its cost stay hidden; a deactivated template is not offered on new quotes."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, flt, today

from smart_power.sp_quotes import payment_plans as pp
from smart_power.tests.utils import make_quotation, set_setting

PLAN_A, PLAN_B = "SP60 12 months", "SP60 24 months"


def template(**kw):
	return frappe._dict(
		{
			"name": "t",
			"cash_multiplier": 0,
			"down_payment_pct": 0,
			"months": 12,
			"every_months": 1,
			"finance_service_pct": 0,
			"price_build": pp.TOGETHER,
			"service_basis": pp.YEARLY,
			"cheque_uplift_type": pp.PERCENT,
			"cheque_uplift": 0,
			**kw,
		}
	)


def make_template(name, **kw):
	if frappe.db.exists(pp.TEMPLATE, name):
		frappe.delete_doc(pp.TEMPLATE, name, force=True)
	return frappe.get_doc(
		{"doctype": pp.TEMPLATE, "plan_name": name, "is_active": 1, "months": 12, **kw}
	).insert()


class TestPaymentPlans(IntegrationTestCase):
	def setUp(self):
		set_setting(cost_of_money_pct=20)
		frappe.db.set_value(pp.TEMPLATE, {"name": ("not in", [PLAN_A, PLAN_B])}, "is_active", 0)

	def test_the_contribution_and_its_cost(self):
		# installment price 220,000 (200,000 x 1.1), down payment 120,000, cost 150,000
		t = template(cash_multiplier=1.1, down_payment_pct=600 / 11, months=12)
		plan = pp.compute(t, 200000, 150000, today())
		self.assertEqual((plan.plan_total, plan.down_payment), (220000, 120000))
		self.assertEqual(plan.contribution, 30000)
		self.assertEqual(plan.contribution_cost, 6000)  # 30,000 x 20% x 12 / 12
		self.assertEqual(plan.net_profit, 220000 - 150000 - 6000)
		# the cost of money follows the plan's months
		self.assertEqual(
			pp.compute(
				template(cash_multiplier=1.1, down_payment_pct=600 / 11, months=24), 200000, 150000
			).contribution_cost,
			12000,
		)

	def test_service_flags(self):
		financed = 80000  # 100,000 with 20% down
		yearly = pp.compute(template(down_payment_pct=20, finance_service_pct=10, months=24), 100000)
		self.assertEqual(yearly.plan_total, 100000 + financed * 0.10 * 2)
		once = pp.compute(
			template(down_payment_pct=20, finance_service_pct=10, months=24, service_basis=pp.ONCE), 100000
		)
		self.assertEqual(once.plan_total, 100000 + financed * 0.10)
		both = pp.compute(template(cash_multiplier=1.2, finance_service_pct=10, months=12), 100000)
		self.assertEqual(both.plan_total, 120000 + 120000 * 0.10)
		alternatives = pp.compute(
			template(cash_multiplier=1.2, finance_service_pct=10, months=12, price_build=pp.ALTERNATIVES),
			100000,
		)
		self.assertEqual(alternatives.plan_total, 120000)

	def test_schedule_and_cheques(self):
		plan = pp.compute(
			template(down_payment_pct=25, months=12, every_months=3, cheque_uplift=5),
			100000,
			start="2027-01-01",
		)
		rows = json.loads(plan.schedule)
		self.assertEqual(plan.installments, 4)
		self.assertEqual(
			[r["due_date"] for r in rows],
			["2027-01-01", *[str(add_months("2027-01-01", 3 * k)) for k in range(1, 5)]],
		)
		self.assertEqual(flt(sum(r["amount"] for r in rows), 2), plan.plan_total)
		self.assertEqual((plan.installment_amount, plan.cheque_amount), (18750, 19687.5))
		amount = pp.compute(template(months=10, cheque_uplift_type=pp.AMOUNT, cheque_uplift=250), 10000)
		self.assertEqual((amount.installment_amount, amount.cheque_amount), (1000, 1250))

	def test_a_deactivated_plan_leaves_new_quotes_old_ones_keep_it(self):
		make_template(PLAN_A, months=12, down_payment_pct=30)
		make_template(PLAN_B, months=24, down_payment_pct=20, finance_service_pct=10)
		old = make_quotation(save=False)
		old.insert()
		self.assertEqual([r.template for r in old.sp_payment_plans], [PLAN_A, PLAN_B])
		old.submit()
		frappe.db.set_value(pp.TEMPLATE, PLAN_B, "is_active", 0)
		new = make_quotation()
		self.assertEqual([r.template for r in new.sp_payment_plans], [PLAN_A])
		old.reload()
		self.assertEqual([r.template for r in old.sp_payment_plans], [PLAN_A, PLAN_B])

	def test_the_customer_picks_a_plan_on_the_sent_quote(self):
		make_template(PLAN_A, months=12, down_payment_pct=30)
		q = make_quotation()
		q.submit()
		q.reload()
		q.sp_payment_plan = PLAN_A
		q.save()
		self.assertEqual(frappe.db.get_value("Quotation", q.name, "sp_payment_plan"), PLAN_A)

	def test_the_financing_cost_is_hidden(self):
		meta = frappe.get_meta("SP Quote Payment Plan")
		for field in ("contribution", "contribution_cost", "net_profit", "net_margin_pct"):
			self.assertEqual(meta.get_field(field).permlevel, 2)

	def test_a_plan_below_the_margin_range_is_listed(self):
		from smart_power.rules import evaluate
		from smart_power.rules.sales import QUOTE_SEND_EVENT

		set_setting(margin_ranges=[{"scope": "Supply and install", "min_pct": 9, "max_pct": 50}])
		make_template(PLAN_A, months=24)  # no down payment: the whole cost is the company's for 2 years
		q = make_quotation(save=False)
		for row in q.items:
			row.sp_cost = row.rate * 0.85  # 15% gross margin, in range
		q.insert()
		hits = [h.spec.key for h in evaluate(q, QUOTE_SEND_EVENT)]
		self.assertIn("quote_plan_margin", hits)  # 15% less 40% x 2 years of cost of money
		self.assertNotIn("quote_margin_range", hits)
