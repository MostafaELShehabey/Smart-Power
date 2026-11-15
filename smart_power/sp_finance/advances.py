"""Customer advances, Agri Bank (A8, SP-121; journey J9).

When a contract is financed by the Agri Bank, the company pays the customer's own share for them
and the bank (or the customer) pays it back later. Those advances are tracked apart from the
station's price: they sit on their own asset account, Customer Advances - Agri Bank, never on
Debtors, so the station's Remaining does not move.

    the contract (D1) is financed by the Agri Bank  → the admin gets a task to record it
    record + submit   Dr Customer Advances (the station's project) / Cr the official account
    add_repayment     Dr the official account / Cr Customer Advances          (Advance Repayment)
                      + an optional fee: Dr the official account / Cr Advance Fees (Advance Fee)
    mark_unpaid       an advance the bank has not released in time keeps a note

Status: Open → Partly repaid → Repaid; or Unpaid - overdue (marked, until it is repaid).
The accounts come from the Account Map (events Customer Advance, Advance Repayment, Advance Fee);
the official account is the advance's own (paid from, or the repayment's to account).
Advances show on AR1 (SP-120) and in the station's connections.
"""

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.utils import flt, getdate, now_datetime, today

from smart_power.sp_finance.accounts import OFFICIAL

ADVANCE, STATION, TASK = "SP Customer Advance", "SP Station", "SP Task"
PAID, REPAYMENT, FEE = "Customer Advance", "Advance Repayment", "Advance Fee"
DRAFT, OPEN, PARTLY, REPAID, UNPAID, CANCELLED = (
	"Draft",
	"Open",
	"Partly repaid",
	"Repaid",
	"Unpaid - overdue",
	"Cancelled",
)
AGRI_BANK = "Financing Type-AGRI"
RECORDERS = ("SP Admin", "System Manager", "SP Bank Financing")
TASK_TYPE, TASK_OPEN, TASK_DONE = "Agri Bank Advance", "Open", "Done"
ROUNDING = 0.005  # sp-allow-number: half a piastre


def can_record(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(RECORDERS) & set(frappe.get_roles(user)))


def _official(account: str | None, label: str) -> None:
	if account and frappe.db.get_value("Account", account, "sp_account_kind") != OFFICIAL:
		frappe.throw(_("{0} must be an official account (a bank, the Post, InstaPay …).").format(_(label)))


# --- the document ------------------------------------------------------------------------------


def validate(doc) -> None:
	station = frappe.db.get_value(
		STATION, doc.station, ["customer", "customer_name", "company", "project"], as_dict=True
	)
	if station:
		doc.customer, doc.customer_name = station.customer, station.customer_name
		doc.company, doc.project = station.company, station.project
	if flt(doc.amount) <= 0:
		frappe.throw(_("The amount must be above zero."))
	_official(doc.paid_from_account, "Paid From")
	if doc.docstatus.is_draft():
		doc.status = DRAFT
	_totals(doc)


def _totals(doc) -> None:
	doc.repaid_amount = sum(flt(r.amount) for r in doc.repayments)
	doc.fee_amount = sum(flt(r.fee_amount) for r in doc.repayments)
	doc.outstanding_amount = max(flt(doc.amount) - flt(doc.repaid_amount), 0.0)


def _status(doc) -> str:
	if doc.docstatus.is_draft():
		return DRAFT
	if doc.docstatus.is_cancelled():
		return CANCELLED
	if flt(doc.outstanding_amount) <= ROUNDING:
		return REPAID
	if doc.status == UNPAID:
		return UNPAID
	return PARTLY if flt(doc.repaid_amount) > 0 else OPEN


def on_submit(doc) -> None:
	from smart_power.sp_finance.posting import post

	if not can_record():
		frappe.throw(_("Only the admin or bank financing records an advance."), frappe.PermissionError)
	entry = post(
		PAID,
		doc,
		flt(doc.amount),
		posting_date=doc.paid_on,
		project=doc.project,
		credit_account=doc.paid_from_account,
		remark=_("Advance {0} for station {1} ({2})").format(doc.name, doc.station, doc.customer_name or ""),
	)
	doc.db_set({"journal_entry": entry, "status": OPEN})
	_close_tasks(doc.station)


def on_cancel(doc) -> None:
	"""Its entries (the advance, every repayment and fee) are cancelled by SP-113's hook."""
	doc.db_set("status", CANCELLED)


# --- actions on a posted advance ----------------------------------------------------------------


def _posted(name: str):
	if not can_record():
		frappe.throw(_("Only the admin or bank financing changes an advance."), frappe.PermissionError)
	doc = frappe.get_doc(ADVANCE, name)
	if doc.docstatus != 1:
		frappe.throw(_("Submit the advance first."))
	return doc


@frappe.whitelist(methods=["POST"])
def add_repayment(
	name: str,
	to_account: str,
	amount: float = 0,
	fee_amount: float = 0,
	repayment_date: str | None = None,
	reference: str | None = None,
) -> dict:
	"""The bank released the loan or the customer paid: the repayment, with an optional fee."""
	from smart_power.sp_finance.posting import post

	doc = _posted(name)
	amount, fee_amount = flt(amount), flt(fee_amount)
	if amount < 0 or fee_amount < 0 or not (amount or fee_amount):
		frappe.throw(_("Enter the amount repaid, the fee, or both."))
	if amount > flt(doc.outstanding_amount) + ROUNDING:
		frappe.throw(
			_("Only {0} is outstanding on this advance.").format(
				frappe.format(doc.outstanding_amount, "Currency")
			)
		)
	if not to_account:
		frappe.throw(_("Choose the account the money came into."), frappe.MandatoryError)
	_official(to_account, "To Account")
	when = getdate(repayment_date or today())
	label = _("advance {0}, station {1}").format(doc.name, doc.station)
	row = doc.append(
		"repayments",
		{
			"repayment_date": when,
			"amount": amount,
			"fee_amount": fee_amount,
			"to_account": to_account,
			"reference": reference,
		},
	)
	if amount:
		row.journal_entry = post(
			REPAYMENT,
			doc,
			amount,
			posting_date=when,
			project=doc.project,
			debit_account=to_account,
			remark=_("Repayment of {0}").format(label),
		)
	if fee_amount:
		row.fee_entry = post(
			FEE,
			doc,
			fee_amount,
			posting_date=when,
			project=doc.project,
			debit_account=to_account,
			remark=_("Fee on {0}").format(label),
		)
	_totals(doc)
	doc.status = _status(doc)
	doc.flags.ignore_permissions = True  # checked by _posted
	doc.save()
	return {"status": doc.status, "outstanding_amount": doc.outstanding_amount}


@frappe.whitelist(methods=["POST"])
def mark_unpaid(name: str, note: str) -> str:
	"""Not released in time: the advance is Unpaid - overdue, with the reason, until it is repaid."""
	note = (note or "").strip()
	if not note:
		frappe.throw(_("Write a note: why is it unpaid?"), frappe.MandatoryError)
	doc = _posted(name)
	if doc.status == REPAID:
		frappe.throw(_("This advance is repaid."))
	doc.status = UNPAID
	doc.note = "\n".join(part for part in (doc.note, f"{today()}: {note}") if part)
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.status


# --- the contract's task (D1) ------------------------------------------------------------------


def on_contract(so, method=None) -> None:
	"""Sales Order on_submit: a contract financed by the Agri Bank asks the admin to record the advance."""
	from smart_power.sp_sales.quote_request import _users_with

	if so.get("sp_financing_type") != AGRI_BANK or not so.get("sp_station"):
		return
	if frappe.db.exists(ADVANCE, {"station": so.sp_station, "docstatus": ("<", DocStatus.cancelled())}):
		return
	users = sorted(set(_users_with("SP Bank Financing")) | set(_users_with("SP Admin"))) or ["Administrator"]
	for user in users:
		frappe.get_doc(
			{
				"doctype": TASK,
				"subject": _("Record the Agri Bank advance for station {0} ({1})").format(
					so.sp_station, so.customer_name or so.customer
				),
				"task_type": TASK_TYPE,
				"assigned_to": user,
				"reference_doctype": STATION,
				"reference_name": so.sp_station,
			}
		).insert(ignore_permissions=True)


def _close_tasks(station: str) -> None:
	for name in frappe.get_all(
		TASK,
		{
			"reference_doctype": STATION,
			"reference_name": station,
			"task_type": TASK_TYPE,
			"status": TASK_OPEN,
		},
		pluck="name",
	):
		frappe.db.set_value(
			TASK,
			name,
			{"status": TASK_DONE, "completed_by": frappe.session.user, "completed_on": now_datetime()},
		)


# --- the Account Map rows ------------------------------------------------------------------------


def seed_account_map(company: str) -> None:
	"""The three advance events in the Account Map, once (the admin may change them)."""
	from smart_power.constants import SETTINGS_DOCTYPE

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	have = {r.event for r in settings.account_map}

	def account(name: str) -> str | None:
		return frappe.db.get_value("Account", {"company": company, "account_name": name, "is_group": 0})

	advances, fees = account("Customer Advances - Agri Bank"), account("Advance Fees")
	official = frappe.db.get_value(
		"Account",
		{"company": company, "sp_account_kind": OFFICIAL, "is_group": 0, "disabled": 0},
		order_by="account_name asc",
	)
	center = frappe.get_cached_value("Company", company, "cost_center")
	if not (advances and fees and official and center):
		return
	note = "The official account comes from the advance."
	rows = {
		PAID: (advances, official, "Debit side"),
		REPAYMENT: (official, advances, "Credit side"),
		FEE: (official, fees, "None"),
	}
	added = False
	for event, (debit, credit, project_rule) in rows.items():
		if event in have:
			continue
		settings.append(
			"account_map",
			{
				"event": event,
				"debit_account": debit,
				"debit_center_rule": "Fixed",
				"debit_cost_center": center,
				"credit_account": credit,
				"credit_center_rule": "Fixed",
				"credit_cost_center": center,
				"project_rule": project_rule,
				"note": note,
			},
		)
		added = True
	if added:
		settings.flags.ignore_permissions = True
		settings.save()
