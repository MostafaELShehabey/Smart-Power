"""Quotation rules for Smart Power (SP-54).

A Smart Power quote belongs to an SP Case: its customer is the case's customer, and every
saved or submitted version marks an action on the case (for the inactivity rule, SP-71).

Versions are separate Quotations on the same case, numbered v1, v2 …. "New Version" copies a
quote into a new draft; "Approve Version" marks the submitted version the customer accepted
and records it on the case (the contract is made from it, SP-74).
"""

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Max
from frappe.utils import add_days, getdate, today

from smart_power.sp_core.services.settings import get_value
from smart_power.sp_sales.case import touch

CASE = "SP Case"
APPROVE_ROLES = ("SP Admin", "System Manager")
CLOSED_STATUSES = ("Won", "Lost")


def validate(doc, method=None) -> None:
	"""Quotation validate hook."""
	check_case(doc)
	set_valid_till(doc)


def set_valid_till(doc) -> None:
	"""An empty Valid Till comes from Quote Validity (days) in Smart Power Settings; the
	quote_validity rule caps it at the maximum."""
	days = get_value("validity_days")
	if not doc.get("valid_till") and days and doc.get("transaction_date"):
		doc.valid_till = add_days(doc.transaction_date, int(days))


def before_insert(doc, method=None) -> None:
	"""Number the version: one more than the case's highest."""
	if doc.get("sp_case"):
		quotation = DocType("Quotation")
		highest = (
			frappe.qb.from_(quotation)
			.select(Max(quotation.sp_version))
			.where(quotation.sp_case == doc.sp_case)
			.run()[0][0]
		)
		doc.sp_version = int(highest or 0) + 1


def on_cancel(doc, method=None) -> None:
	"""A cancelled approved version is no longer the case's accepted quote."""
	if doc.get("sp_is_approved") and doc.get("sp_case"):
		doc.db_set("sp_is_approved", 0)
		if frappe.db.get_value(CASE, doc.sp_case, "accepted_quotation") == doc.name:
			frappe.db.set_value(CASE, doc.sp_case, "accepted_quotation", None)


def on_update(doc, method=None) -> None:
	if doc.get("sp_case"):
		touch(doc.sp_case)


def check_case(doc) -> None:
	"""The quote is for the case's customer."""
	if not doc.get("sp_case"):
		return
	customer = frappe.db.get_value(CASE, doc.sp_case, "customer")
	if doc.quotation_to != "Customer" or doc.party_name != customer:
		frappe.throw(
			_("This quote is for {0}, but case {1} is for customer {2}.").format(
				frappe.bold(doc.party_name), frappe.bold(doc.sp_case), frappe.bold(customer)
			),
			title=_("Wrong customer"),
		)


@frappe.whitelist(methods=["POST"])
def new_version(quotation: str) -> str:
	"""Copy a quote of a case into a new draft version, dated today."""
	source = frappe.get_doc("Quotation", quotation)
	source.check_permission("read")
	if not source.get("sp_case"):
		frappe.throw(_("Only a quote linked to a case has versions."))
	frappe.has_permission("Quotation", "create", throw=True)
	doc = frappe.copy_doc(source, ignore_no_copy=False)  # no flags or approval carried over
	doc.sp_previous_version = source.name
	doc.transaction_date = today()
	doc.valid_till = None
	doc.insert()
	return doc.name


@frappe.whitelist(methods=["POST"])
def approve_version(quotation: str) -> str:
	"""Mark the submitted version the customer accepted, and record it on the case."""
	doc = frappe.get_doc("Quotation", quotation)
	if not doc.get("sp_case"):
		frappe.throw(_("Only a quote linked to a case can be the approved version."))
	if not doc.docstatus.is_submitted():
		frappe.throw(_("Submit the quote before approving it."))
	case = frappe.db.get_value(
		CASE, doc.sp_case, ["status", "follow_up_owner", "quote_creator", "accepted_quotation"], as_dict=True
	)
	if not _can_approve(case):
		frappe.throw(
			_("Only the case's follow-up owner, its quote creator or the admin can approve a version."),
			frappe.PermissionError,
		)
	if case.status in CLOSED_STATUSES:
		frappe.throw(
			_("Case {0} is {1}; its approved version cannot change.").format(doc.sp_case, _(case.status))
		)
	check_can_approve(doc)
	for other in frappe.get_all(
		"Quotation", {"sp_case": doc.sp_case, "sp_is_approved": 1, "name": ("!=", doc.name)}, pluck="name"
	):
		frappe.db.set_value("Quotation", other, "sp_is_approved", 0)
	doc.db_set("sp_is_approved", 1)
	frappe.db.set_value(CASE, doc.sp_case, "accepted_quotation", doc.name)
	touch(doc.sp_case)
	return doc.name


def check_can_approve(doc) -> None:
	"""An expired version, or one that needs repricing, is not approved: make a new version."""
	if doc.get("sp_needs_repricing"):
		frappe.throw(
			_("This version needs repricing ({0}). Make a new version at today's prices.").format(
				doc.get("sp_repricing_note") or _("prices changed")
			)
		)
	if doc.get("valid_till") and getdate(doc.valid_till) < getdate(today()):
		frappe.throw(
			_("This version expired on {0}. Make a new version.").format(
				frappe.format(doc.valid_till, "Date")
			)
		)


def mark_needs_repricing(quotation: str, note: str) -> None:
	"""Flag a quote whose prices changed or that expired before the deposit (SP-170's job)."""
	frappe.db.set_value("Quotation", quotation, {"sp_needs_repricing": 1, "sp_repricing_note": note})


def _can_approve(case) -> bool:
	user = frappe.session.user
	if user == "Administrator" or set(APPROVE_ROLES) & set(frappe.get_roles(user)):
		return True
	return user in (case.follow_up_owner, case.quote_creator)
