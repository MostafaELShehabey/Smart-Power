"""Installment plans on quotes (SP-60): one option per active Payment Plan Template.

For a quote's cash price C and cost K, a template gives (its flags are the owner's answers to
the formula questions of SP-158, so an answer changes data, not code):

    price      = C x multiplier                        (C when there is no multiplier)
    down       = price x down payment %
    financed   = price - down
    service    = financed x service % x months / 12    ("Yearly x months")
               = financed x service %                  ("Once")
                 none when the plan prices by "Alternatives" and has a multiplier
    total      = price + service
    n          = months / every N months               (at least one installment)
    installment = (total - down) / n, due every N months from the quote date
    cheque     = installment x (1 + uplift %)  or  installment + uplift amount

and, hidden at the cost permlevel (SP-35):

    contribution      = K - down, when positive
    contribution cost = contribution x annual cost of money % x months / 12
    net profit        = total - K - contribution cost;   net margin = net profit / total

A draft quote is re-planned on every save from the active templates; a sent version keeps the
plans it was sent with, so deactivating a template changes no old quote. The rule
quote_plan_margin (rules.sales) lists a plan whose net margin falls below the offer type's range.
"""

import json

import frappe
from frappe.utils import add_months, cint, flt, getdate, today

from smart_power.sp_core.services.settings import get_value

TEMPLATE = "SP Payment Plan Template"
TOGETHER, ALTERNATIVES = "Together", "Alternatives"
YEARLY, ONCE = "Yearly x months", "Once"
PERCENT, AMOUNT = "Percent", "Amount"
PCT, MONTHS_PER_YEAR = 100, 12  # sp-allow-number: percent and calendar facts
MONEY = 2  # sp-allow-number: amounts to the piastre


def compute(template, cash: float, cost: float = 0, start=None) -> frappe._dict:
	"""One plan for a cash price (and cost): totals, schedule, cheque value and financing cost."""
	t = frappe.get_cached_doc(TEMPLATE, template) if isinstance(template, str) else template
	start = getdate(start or today())
	months = max(cint(t.months), 1)
	every = max(cint(t.every_months) or 1, 1)
	multiplier = flt(t.cash_multiplier)
	price = flt(cash) * multiplier if multiplier else flt(cash)
	down = flt(price * flt(t.down_payment_pct) / PCT, MONEY)
	financed = price - down
	service = 0.0
	if flt(t.finance_service_pct) and not (t.price_build == ALTERNATIVES and multiplier):
		years = months / MONTHS_PER_YEAR if (t.service_basis or YEARLY) == YEARLY else 1
		service = financed * flt(t.finance_service_pct) / PCT * years
	total = flt(price + service, MONEY)
	n = max(months // every, 1)
	installment = flt((total - down) / n, MONEY)
	uplift = flt(t.cheque_uplift)
	cheque = installment + uplift if t.cheque_uplift_type == AMOUNT else installment * (1 + uplift / PCT)
	dues = [add_months(start, every * k) for k in range(1, n + 1)]
	schedule = [{"due_date": str(start), "amount": down, "kind": "down"}] if down else []
	# the last installment takes the rounding, so the schedule adds up to the total
	amounts = [installment] * (n - 1) + [flt(total - down - installment * (n - 1), MONEY)]
	schedule += [
		{"due_date": str(d), "amount": a, "kind": "installment"} for d, a in zip(dues, amounts, strict=True)
	]
	contribution = max(flt(cost) - down, 0)
	rate = flt(get_value("cost_of_money_pct"))
	contribution_cost = flt(contribution * rate / PCT * months / MONTHS_PER_YEAR, MONEY)
	net_profit = flt(total - flt(cost) - contribution_cost, MONEY)
	return frappe._dict(
		template=t.name,
		plan_total=total,
		down_payment=down,
		installments=n,
		installment_amount=installment,
		cheque_amount=flt(cheque, MONEY),
		first_due=str(dues[0]),
		last_due=str(dues[-1]),
		schedule=json.dumps(schedule),
		contribution=flt(contribution, MONEY),
		contribution_cost=contribution_cost,
		net_profit=net_profit,
		net_margin_pct=flt(net_profit / total * PCT, MONEY) if total else 0,
	)


def active_templates() -> list[str]:
	return frappe.get_all(TEMPLATE, {"is_active": 1}, pluck="name", order_by="plan_name asc")


def set_quote_plans(doc, method=None) -> None:
	"""Quotation validate: a draft of a case gets one plan per active template; a sent version
	keeps the plans it was sent with."""
	if not doc.get("sp_case") or cint(doc.docstatus) != 0:
		return
	cash = flt(doc.get("rounded_total") or doc.get("grand_total"))
	if not cash:
		doc.set("sp_payment_plans", [])
		return
	cost = flt(doc.get("sp_total_cost"))
	start = doc.get("transaction_date") or today()
	doc.set("sp_payment_plans", [compute(name, cash, cost, start) for name in active_templates()])
	if doc.get("sp_payment_plan") and doc.sp_payment_plan not in active_templates():
		doc.sp_payment_plan = None  # the chosen plan is no longer offered


def schedule_of(row) -> list[dict]:
	return json.loads(row.schedule or "[]")
