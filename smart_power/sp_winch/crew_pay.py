"""Worker advances and crew salaries for the winch and Jumbo car (SP-181).

A crew member can be given an advance, paid back in installments, and the salaried crew are paid
monthly on their vehicle's center. Worker Advance Repayment (Smart Power Settings) says how an
advance is paid back: deducted from each monthly salary (the default), or in cash. Daily workers
are paid through the field entry's Worker Wage (SP-108), so theirs are always repaid in cash.

    advance submitted   Dr Worker Advances / Cr the account it was paid from        (Worker Advance)
    cash repayment      Dr the account it was paid into / Cr Worker Advances  (Worker Advance Repayment)
    salary submitted    Dr Crew Salaries / Cr the account it was paid from, what was paid (Crew Salary)
                        Dr Crew Salaries / Cr Worker Advances, the installments     (Advance Deduction)

A salary deducts each open advance's installment, oldest first, never more than what is still
owed or than the salary itself. Cancelling the salary gives those installments back. The balance
of each worker is the sum of his open advances' outstanding (worker_balance).
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate

from smart_power.sp_finance.posting import post
from smart_power.sp_finance.queries import picker_accounts
from smart_power.sp_winch.field_entry import _has_role, _run_as

ADVANCE, REPAYMENT, SALARY, EMPLOYEE, VEHICLE = (
	"SP Worker Advance",
	"SP Worker Advance Repayment",
	"SP Crew Salary",
	"Employee",
	"Vehicle",
)
DRAFT, OPEN, REPAID, CANCELLED = "Draft", "Open", "Repaid", "Cancelled"
DEDUCTION, CASH = "Salary deduction", "Cash"
ADVANCE_EVENT, REPAYMENT_EVENT, SALARY_EVENT, DEDUCTION_EVENT = (
	"Worker Advance",
	"Worker Advance Repayment",
	"Crew Salary",
	"Advance Deduction",
)
ADVANCES_ACCOUNT, SALARIES_ACCOUNT, SHOP_ACCOUNT = "Worker Advances", "Crew Salaries", "Showroom Safe"
PAYERS = ("SP Winch Manager", "SP Admin", "System Manager")
CANCELLED_DOC = 2  # sp-allow-number: Frappe's docstatus of a cancelled document
PENNY = 0.005  # sp-allow-number: half a piastre, rounding


def repayment_mode() -> str:
	from smart_power.sp_core.services.settings import get_value

	return get_value("worker_advance_repayment") or DEDUCTION


def _check_payer() -> None:
	if not _has_role(PAYERS):
		frappe.throw(_("Only the winch manager or the admin pays the crew."), frappe.PermissionError)


def _vehicle(doc) -> None:
	row = frappe.db.get_value(VEHICLE, doc.vehicle, ["company", "sp_cost_center"], as_dict=True)
	if not row:
		frappe.throw(_("Choose the vehicle."))
	doc.company = row.company
	doc.cost_center = row.sp_cost_center or frappe.get_cached_value("Company", row.company, "cost_center")


def _money_account(account: str | None, company: str, label: str) -> None:
	if account not in picker_accounts(company):
		frappe.throw(
			_("{0}: choose an official account, or your own cash or custody.").format(_(label)),
			frappe.ValidationError,
		)


def _account(company: str, account_name: str) -> str | None:
	return frappe.db.get_value("Account", {"company": company, "account_name": account_name, "is_group": 0})


# --- the advance -------------------------------------------------------------------------------


def validate_advance(doc) -> None:
	if flt(doc.amount) <= 0:
		frappe.throw(_("The amount must be above zero."))
	if flt(doc.installment_amount) <= 0 or flt(doc.installment_amount) > flt(doc.amount):
		frappe.throw(_("The installment must be above zero and no more than the advance."))
	_vehicle(doc)
	if doc.docstatus == 0:
		_money_account(doc.paid_from, doc.company, "Paid From")
		doc.status = DRAFT
	_totals(doc)


def _totals(doc) -> None:
	doc.repaid_amount = sum(flt(r.amount) for r in doc.repayments)
	doc.outstanding_amount = max(flt(doc.amount) - flt(doc.repaid_amount), 0.0)
	if doc.docstatus == 1:
		doc.status = REPAID if doc.outstanding_amount <= PENNY else OPEN


def submit_advance(doc) -> None:
	_run_as(
		"Administrator",
		lambda: post(
			ADVANCE_EVENT,
			doc,
			flt(doc.amount),
			company=doc.company,
			posting_date=doc.work_date,
			remark=_("Advance to {0}").format(doc.employee_name or doc.employee),
			cost_center=doc.cost_center,
			credit_account=doc.paid_from,
		),
	)
	doc.db_set("status", OPEN)


def cancel_advance(doc) -> None:
	if doc.repayments:
		frappe.throw(_("Part of this advance is repaid: cancel the repayments first."))
	doc.db_set("status", CANCELLED)


def _save_totals(name: str) -> None:
	doc = frappe.get_doc(ADVANCE, name)
	_totals(doc)
	doc.db_set(
		{
			"repaid_amount": doc.repaid_amount,
			"outstanding_amount": doc.outstanding_amount,
			"status": doc.status,
		}
	)


@frappe.whitelist(methods=["POST"])
def repay_in_cash(name: str, amount: float, to_account: str, repayment_date: str | None = None) -> str:
	"""The worker pays back part of the advance in cash: it goes into the account given."""
	_check_payer()
	doc = frappe.get_doc(ADVANCE, name)
	if doc.docstatus != 1 or doc.status != OPEN:
		frappe.throw(_("Advance {0} is not open.").format(name))
	amount = flt(amount)
	if amount <= 0 or amount > flt(doc.outstanding_amount) + PENNY:
		frappe.throw(
			_("Repay above zero and up to the {0} still owed.").format(
				frappe.format(doc.outstanding_amount, "Currency")
			)
		)
	_money_account(to_account, doc.company, "To Account")
	day = getdate(repayment_date) if repayment_date else getdate()
	entry = _run_as(
		"Administrator",
		lambda: post(
			REPAYMENT_EVENT,
			doc,
			amount,
			company=doc.company,
			posting_date=day,
			remark=_("Advance repaid by {0}").format(doc.employee_name or doc.employee),
			cost_center=doc.cost_center,
			debit_account=to_account,
		),
	)
	row = doc.append(
		"repayments",
		{
			"repayment_date": day,
			"kind": CASH,
			"amount": amount,
			"to_account": to_account,
			"journal_entry": entry,
		},
	)
	row.db_insert()
	_save_totals(doc.name)
	return entry


def open_advances(employee: str) -> list:
	"""The worker's open advances, oldest first: what a salary deducts from."""
	return frappe.get_all(
		ADVANCE,
		filters={"employee": employee, "docstatus": 1, "status": OPEN},
		fields=["name", "installment_amount", "outstanding_amount"],
		order_by="work_date asc, creation asc",
	)


@frappe.whitelist()
def worker_balance(employee: str) -> float:
	"""What the worker still owes on all his advances."""
	frappe.has_permission(ADVANCE, "read", throw=True)
	return sum(flt(a.outstanding_amount) for a in open_advances(employee))


# --- the salary ------------------------------------------------------------------------------


@frappe.whitelist()
def salary_start(employee: str) -> dict:
	"""What a new salary starts with: the monthly salary and what the worker still owes. The winch
	manager pays the crew without reading HR's Employee list."""
	_check_payer()
	row = (
		frappe.db.get_value(EMPLOYEE, employee, ["sp_monthly_salary", "sp_is_daily_worker"], as_dict=True)
		or frappe._dict()
	)
	return {
		"monthly_salary": flt(row.sp_monthly_salary),
		"daily_worker": bool(row.sp_is_daily_worker),
		"owed": sum(flt(a.outstanding_amount) for a in open_advances(employee)),
		"mode": repayment_mode(),
	}


def _plan(doc) -> list[dict]:
	"""Each open advance's installment, oldest first, within the salary and what is owed."""
	if repayment_mode() != DEDUCTION or frappe.db.get_value(EMPLOYEE, doc.employee, "sp_is_daily_worker"):
		return []
	left, plan = flt(doc.gross_amount), []
	for advance in open_advances(doc.employee):
		take = min(flt(advance.installment_amount), flt(advance.outstanding_amount), left)
		if take > PENNY:
			plan.append({"advance": advance.name, "amount": take})
			left -= take
	return plan


def validate_salary(doc) -> None:
	_vehicle(doc)
	doc.month = get_first_day(getdate(doc.month))
	if not flt(doc.gross_amount):
		doc.gross_amount = flt(frappe.db.get_value(EMPLOYEE, doc.employee, "sp_monthly_salary"))
	if flt(doc.gross_amount) <= 0:
		frappe.throw(_("Enter the salary of {0}.").format(doc.employee_name or doc.employee))
	twice = frappe.db.exists(
		SALARY,
		{
			"employee": doc.employee,
			"month": doc.month,
			"docstatus": ("!=", CANCELLED_DOC),
			"name": ("!=", doc.name),
		},
	)
	if twice:
		frappe.throw(
			_("{0} already has the salary of {1}: {2}.").format(
				doc.employee_name or doc.employee, frappe.format(doc.month, "Date"), twice
			)
		)
	if doc.docstatus == 0:
		_money_account(doc.paid_from, doc.company, "Paid From")
	plan = _plan(doc)
	doc.advance_deduction = sum(p["amount"] for p in plan)
	doc.net_amount = flt(doc.gross_amount) - flt(doc.advance_deduction)
	doc.deductions = json.dumps(plan) if plan else None


def submit_salary(doc) -> None:
	plan = json.loads(doc.deductions or "[]")
	remark = _("Salary of {0} for {1}").format(
		doc.employee_name or doc.employee, frappe.format(doc.month, "Date")
	)
	common = {
		"company": doc.company,
		"posting_date": doc.work_date,
		"remark": remark,
		"cost_center": doc.cost_center,
	}

	def record() -> None:
		if flt(doc.net_amount) > PENNY:
			post(SALARY_EVENT, doc, flt(doc.net_amount), credit_account=doc.paid_from, **common)
		for part in plan:
			entry = post(DEDUCTION_EVENT, doc, flt(part["amount"]), **common)
			advance = frappe.get_doc(ADVANCE, part["advance"])
			row = advance.append(
				"repayments",
				{
					"repayment_date": doc.work_date,
					"kind": DEDUCTION,
					"amount": flt(part["amount"]),
					"salary": doc.name,
					"journal_entry": entry,
				},
			)
			row.db_insert()
			_save_totals(advance.name)

	_run_as("Administrator", record)


def cancel_salary(doc) -> None:
	"""Its postings are cancelled with it (posting.cancel_postings); the installments come back."""
	rows = frappe.get_all(REPAYMENT, {"salary": doc.name, "parenttype": ADVANCE}, ["name", "parent"])
	for row in rows:
		frappe.db.delete(REPAYMENT, {"name": row.name})
	for advance in {r.parent for r in rows}:
		_save_totals(advance)


# --- the Account Map ----------------------------------------------------------------------------


def seed_account_map(company: str) -> None:
	"""The crew pay rows of the Account Map, once. The admin can change any of them."""
	from smart_power.constants import SETTINGS_DOCTYPE

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	have = {r.event for r in settings.account_map}
	default = frappe.get_cached_value("Company", company, "cost_center")
	advances, salaries, shop = (
		_account(company, n) for n in (ADVANCES_ACCOUNT, SALARIES_ACCOUNT, SHOP_ACCOUNT)
	)
	rows = (
		(ADVANCE_EVENT, advances, shop, "The credit is the account the advance was paid from."),
		(REPAYMENT_EVENT, shop, advances, "The debit is the account the cash was paid into."),
		(SALARY_EVENT, salaries, shop, "The credit is the account the salary was paid from."),
		(DEDUCTION_EVENT, salaries, advances, "An advance installment taken off a salary."),
	)
	changed = False
	for event, debit, credit, note in rows:
		if event in have or not (debit and credit and default):
			continue
		settings.append(
			"account_map",
			{
				"event": event,
				"debit_account": debit,
				"debit_center_rule": "From document",
				"debit_cost_center": default,
				"credit_account": credit,
				"credit_center_rule": "From document",
				"credit_cost_center": default,
				"project_rule": "None",
				"note": note,
			},
		)
		changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.save()
