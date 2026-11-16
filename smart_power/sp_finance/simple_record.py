"""G7 Simple record (SP-43): the rules of SP Simple Record.

A type (list "Simple Record Type") says which account it posts against and whether money
usually comes in or goes out (its meta: {"account": ..., "direction": "In" | "Out"}). When money
moved, the record posts through the Account Map's "Simple Record" event (SP-113):

    Money In    Dr the record's account (a bank, a cash box)   Cr the type's account (an income)
    Money Out   Dr the type's account (an expense)             Cr the record's account

both lines on the record's center (a station's: Projects, with its project).
"""

import json

import frappe
from frappe import _
from frappe.utils import flt

EVENT = "Simple Record"
LIST = "Simple Record Type"
IN, OUT, NONE = "Money In", "Money Out", "None"
# a type's meta says In or Out
META_DIRECTION = {"In": IN, "Out": OUT}


def _meta(record_type: str) -> dict:
	meta = frappe.db.get_value("SP List Value", record_type, "meta_json")
	if isinstance(meta, str):
		return json.loads(meta) if meta else {}
	return meta or {}


@frappe.whitelist()
def type_direction(record_type: str) -> str | None:
	"""For the form: the direction the type usually has."""
	frappe.has_permission("SP Simple Record", "create", throw=True)
	return META_DIRECTION.get(_meta(record_type).get("direction"))


def type_account(record_type: str, company: str) -> str:
	"""The account the type posts against (its meta, by account name or full name)."""
	name = _meta(record_type).get("account")
	account = name and (
		frappe.db.get_value("Account", {"company": company, "account_name": name, "is_group": 0})
		or frappe.db.get_value("Account", {"company": company, "name": name, "is_group": 0})
	)
	if not account:
		frappe.throw(
			_("Set the account of the type {0} in Lists (its meta: account).").format(
				frappe.bold(record_type)
			),
			title=_("Simple record"),
		)
	return account


def validate(doc) -> None:
	validate_reason(doc)
	if frappe.db.get_value("SP List Value", doc.record_type, "list_name") != LIST:
		frappe.throw(_("{0} is not a simple record type.").format(frappe.bold(doc.record_type)))
	if doc.station:
		from smart_power.sp_finance.centers import station_center

		doc.project = frappe.db.get_value("SP Station", doc.station, "project")
		doc.cost_center = station_center(doc.company)
	if not doc.cost_center:
		frappe.throw(_("Choose the center or the station."))
	doc.direction = doc.direction or NONE
	if doc.direction == NONE:
		return
	if flt(doc.amount) <= 0:
		frappe.throw(_("Money moved: enter the amount."))
	if not doc.account:
		frappe.throw(_("Money moved: choose the account it moved through."))
	if frappe.db.get_value("Account", doc.account, "company") != doc.company:
		frappe.throw(_("The account {0} is not {1}'s.").format(doc.account, doc.company))


def entry_accounts(doc) -> tuple[str, str]:
	"""(debit, credit) of the record's entry."""
	counter = type_account(doc.record_type, doc.company)
	return (doc.account, counter) if doc.direction == IN else (counter, doc.account)


def post_record(doc) -> str | None:
	"""on_submit: when money moved, post the entry (Account Map: Simple Record)."""
	if doc.direction == NONE or flt(doc.amount) <= 0:
		return None
	from smart_power.sp_finance.posting import post

	debit, credit = entry_accounts(doc)
	entry = post(
		EVENT,
		doc,
		flt(doc.amount),
		posting_date=doc.work_date,
		cost_center=doc.cost_center,
		project=doc.project,
		debit_account=debit,
		credit_account=credit,
		remark=_("{0}: {1}").format(doc.record_type, doc.note or doc.name),
	)
	doc.db_set("journal_entry", entry)
	return entry


def seed_account_map(company: str) -> None:
	"""The Simple Record row of the Account Map, once: both sides from the record (its account,
	its type's account, its center); the station's project on both lines."""
	from smart_power.constants import SETTINGS_DOCTYPE
	from smart_power.sp_finance.accounts import OFFICIAL

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if any(r.event == EVENT for r in settings.account_map):
		return
	official = frappe.db.get_value(
		"Account",
		{"company": company, "sp_account_kind": OFFICIAL, "is_group": 0, "disabled": 0},
		order_by="account_name asc",
	)
	center = frappe.get_cached_value("Company", company, "cost_center")
	if not (official and center):
		return
	settings.append(
		"account_map",
		{
			"event": EVENT,
			"debit_account": official,
			"debit_center_rule": "From document",
			"debit_cost_center": center,
			"credit_account": official,
			"credit_center_rule": "From document",
			"credit_cost_center": center,
			"project_rule": "Both sides",
			"note": "The record's account and its type's account replace these; the center is the record's.",
		},
	)
	settings.flags.ignore_permissions = True
	settings.save()


# --- changed with a reason: reverse the old entry, post the new one ------------------------------

# what an amended record compares with the record it replaces
WATCHED = ("work_date", "record_type", "amount", "direction", "account", "cost_center", "station")


def validate_reason(doc) -> None:
	if doc.amended_from and not (doc.edit_reason or "").strip():
		frappe.throw(
			_("Give the reason for changing {0}.").format(doc.amended_from), title=_("Reason needed")
		)


def reverse_record(doc) -> str | None:
	"""on_cancel: its entry stays as posted; a new entry with the sides swapped reverses it."""
	if not doc.journal_entry or frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus") != 1:
		return None
	old = frappe.get_doc("Journal Entry", doc.journal_entry)
	reversal = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": old.company,
			"posting_date": frappe.utils.nowdate(),
			"reversal_of": old.name,
			"user_remark": _("Reverses {0}: {1} cancelled").format(old.name, doc.name),
			"sp_posting_event": EVENT,
			"sp_source_doctype": doc.doctype,
			"sp_source_name": doc.name,
			"accounts": [
				{
					"account": line.account,
					"debit_in_account_currency": flt(line.credit_in_account_currency),
					"credit_in_account_currency": flt(line.debit_in_account_currency),
					"cost_center": line.cost_center,
					"project": line.project,
					"party_type": line.party_type,
					"party": line.party,
				}
				for line in old.accounts
			],
		}
	)
	reversal.flags.ignore_permissions = True
	reversal.flags.ignore_links = True  # its source is the record being cancelled, on purpose
	reversal.insert()
	reversal.submit()
	doc.db_set("reversal_entry", reversal.name)
	return reversal.name


def log_change(doc) -> None:
	"""on_submit of an amended record: each changed value with the reason (SP Edit Reason Log),
	in the record's history, and for the admin's review (Edits with reason)."""
	if not doc.amended_from:
		return
	from smart_power.sp_core.review_centre import raise_item
	from smart_power.sp_core.services.audit import log_edit

	old = frappe.get_doc(doc.doctype, doc.amended_from)
	changes = [(f, old.get(f), doc.get(f)) for f in WATCHED if str(old.get(f) or "") != str(doc.get(f) or "")]
	for field, before, after in changes:
		log_edit(doc, field, before, after, doc.edit_reason)
	summary = _("{0} replaces {1}: {2}").format(
		doc.name,
		old.name,
		"; ".join(
			f"{_(doc.meta.get_label(f))} {_shown(doc, f, b)} → {_shown(doc, f, a)}" for f, b, a in changes
		)
		or _("no value changed"),
	)
	doc.add_comment("Info", f"{summary}. {_('Reason')}: {doc.edit_reason}")
	raise_item("Edit", doc, f"{summary}. {doc.edit_reason}", amount=flt(doc.amount))


def _shown(doc, fieldname: str, value) -> str:
	"""A value as the form shows it (1,500.00 rather than 1500.0)."""
	return frappe.format(value, doc.meta.get_field(fieldname)) if value not in (None, "") else "—"
