"""Posting service (SP-113, decisions 1, 3, 34 and 43; tech plan 6-11-2026 section 3 rule 9).

Every money event of Smart Power posts through a standard ERPNext Journal Entry built from the
Account Map in Smart Power Settings: event → debit account and center, credit account and
center, and which side carries the project (the station). The admin edits the map, never code;
a change applies to the next posting only (entries already posted keep their accounts).

    preview(event, doc, amount, ...)   the lines, for the confirmation screen, nothing saved
    post(event, doc, amount, ...)      the submitted Journal Entry's name

Each entry carries its source (sp_source_doctype / sp_source_name) and its event; cancelling
the source cancels its entries (cancel_postings, a doc_events hook on every DocType).
Customer payments post as Payment Entries with SP-114. The admin-editable posting rules (X10)
are R3.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from smart_power.sp_core.services.settings import account_map

JE = "Journal Entry"
FIXED, FROM_DOCUMENT = "Fixed", "From document"
NO_PROJECT, DEBIT_SIDE, CREDIT_SIDE, BOTH_SIDES = "None", "Debit side", "Credit side", "Both sides"


def _company(doc, company: str | None) -> str:
	company = company or doc.get("company") or frappe.defaults.get_user_default("Company")
	company = company or frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		frappe.throw(_("Set the company to post to."))
	return company


def _center(rule: str, fixed: str | None, from_doc: str | None, side: str, event: str) -> str:
	center = from_doc if rule == FROM_DOCUMENT else fixed
	if not center:
		frappe.throw(
			_(
				"Posting {0}: the {1} side has no cost center. Set it in Smart Power Settings > Account Map, or on the document."
			).format(frappe.bold(_(event)), _(side))
		)
	return center


def lines(
	event: str,
	doc,
	amount: float,
	*,
	cost_center: str | None = None,
	project: str | None = None,
	party_type: str | None = None,
	party: str | None = None,
) -> list[dict]:
	"""The two balanced lines of an event, from the Account Map."""
	row = account_map(event)
	if not row:
		frappe.throw(
			_(
				"No account is mapped for {0}. The admin adds it in Smart Power Settings > Account Map."
			).format(frappe.bold(_(event))),
			title=_("Account Map"),
		)
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Posting {0}: the amount must be above zero.").format(frappe.bold(_(event))))
	cost_center = cost_center or doc.get("cost_center")
	project = project or doc.get("project")
	debit = {
		"account": row.debit_account,
		"debit_in_account_currency": amount,
		"credit_in_account_currency": 0,
		"cost_center": _center(row.debit_center_rule, row.debit_cost_center, cost_center, "debit", event),
	}
	credit = {
		"account": row.credit_account,
		"debit_in_account_currency": 0,
		"credit_in_account_currency": amount,
		"cost_center": _center(row.credit_center_rule, row.credit_cost_center, cost_center, "credit", event),
	}
	if project and row.project_rule in (DEBIT_SIDE, BOTH_SIDES):
		debit["project"] = project
	if project and row.project_rule in (CREDIT_SIDE, BOTH_SIDES):
		credit["project"] = project
	for line in (debit, credit):
		if party and frappe.get_cached_value("Account", line["account"], "account_type") in (
			"Receivable",
			"Payable",
		):
			line.update(party_type=party_type, party=party)
	return [debit, credit]


def _entry(event: str, doc, amount: float, *, posting_date=None, company=None, remark=None, **kw):
	return frappe.get_doc(
		{
			"doctype": JE,
			"voucher_type": "Journal Entry",
			"company": _company(doc, company),
			"posting_date": posting_date or doc.get("posting_date") or nowdate(),
			"user_remark": remark or _("{0}: {1}").format(_(event), doc.name),
			"sp_posting_event": event,
			"sp_source_doctype": doc.doctype,
			"sp_source_name": doc.name,
			"accounts": lines(event, doc, amount, **kw),
		}
	)


def preview(event: str, doc, amount: float, **kw) -> list[dict]:
	"""The entry's lines for the confirmation screen; nothing is saved."""
	entry = _entry(event, doc, amount, **kw)
	return [
		{
			"account": line.account,
			"cost_center": line.cost_center,
			"project": line.get("project"),
			"party": line.get("party"),
			"debit": flt(line.debit_in_account_currency),
			"credit": flt(line.credit_in_account_currency),
		}
		for line in entry.accounts
	]


def post(event: str, doc, amount: float, submit: bool = True, **kw) -> str:
	"""Post the event as a Journal Entry from the Account Map; returns its name."""
	entry = _entry(event, doc, amount, **kw)
	entry.flags.ignore_permissions = True  # the confirming user's right is checked by the caller
	entry.insert()
	if submit:
		entry.submit()
	return entry.name


def postings(doc) -> list[str]:
	return frappe.get_all(
		JE, {"sp_source_doctype": doc.doctype, "sp_source_name": doc.name, "docstatus": 1}, pluck="name"
	)


def cancel_postings(doc, method=None) -> None:
	"""on_cancel of any document: its posted entries are cancelled with it."""
	if doc.doctype == JE or not frappe.db.has_column(JE, "sp_source_name"):
		return
	from smart_power.sp_finance.journal import allow_cancel

	for name in postings(doc):
		entry = frappe.get_doc(JE, name)
		allow_cancel(entry)  # the source was cancelled: its entry goes with it (SP-119)
		entry.cancel()
