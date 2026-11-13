"""Quotation rules for Smart Power (SP-54).

A Smart Power quote belongs to an SP Case: its customer is the case's customer, and every
saved or submitted version marks an action on the case (for the inactivity rule, SP-71).

Versions are separate Quotations on the same case, numbered v1, v2 …. "New Version" copies a
quote into a new draft; "Approve Version" marks the submitted version the customer accepted
and records it on the case (the contract is made from it, SP-74).
"""

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.query_builder import DocType
from frappe.query_builder.functions import Max
from frappe.utils import add_days, flt, getdate, today

from smart_power.sp_core.services.settings import get_value
from smart_power.sp_sales.case import touch

CASE = "SP Case"
PCT = 100
APPROVE_ROLES = ("SP Admin", "System Manager")
CLOSED_STATUSES = ("Won", "Lost")
SUBMITTED, CANCELLED = DocStatus.submitted(), DocStatus.cancelled()
DRAFT, SENT, NEEDS_REPRICING, APPROVED, SUPERSEDED, LOST, EXPIRED = (
	"Draft",
	"Sent",
	"Needs repricing",
	"Approved",
	"Superseded",
	"Lost",
	"Expired",
)


def validate(doc, method=None) -> None:
	"""Quotation validate hook."""
	if not doc.get("sp_case"):
		frappe.throw(_("Choose the case this quote belongs to."), frappe.MandatoryError)
	check_case(doc)
	if not doc.get("sp_quote_creator"):
		doc.sp_quote_creator = frappe.db.get_value(CASE, doc.sp_case, "quote_creator")
	if doc.get("_action") == "submit":
		# sending a version: it is dated today and valid for Quote Validity (days) from today
		doc.transaction_date = today()
		doc.valid_till = None
	set_valid_till(doc)
	set_cost_and_profit(doc)
	doc.sp_status = status_of(doc, sending=doc.get("_action") == "submit")


def status_of(doc, sending: bool = False, case_status: str | None = None) -> str:
	"""Draft, Sent, Needs repricing, Approved, Superseded, Lost or Expired."""
	case_status = case_status or frappe.db.get_value(CASE, doc.sp_case, "status")
	submitted = sending or doc.docstatus == SUBMITTED
	if case_status == LOST:
		return LOST
	if not submitted:
		return DRAFT
	if doc.get("sp_is_approved"):
		return APPROVED
	if doc.get("sp_superseded"):
		return SUPERSEDED
	if doc.get("sp_needs_repricing"):
		return NEEDS_REPRICING
	if doc.get("valid_till") and getdate(doc.valid_till) < getdate(today()):
		return EXPIRED
	return SENT


def refresh_status(quotation: str) -> str:
	"""Recompute a quote's status after something outside the quote changed."""
	doc = frappe.get_doc("Quotation", quotation)
	status = status_of(doc)
	if status != doc.get("sp_status"):
		doc.db_set("sp_status", status, update_modified=False)
	return status


def refresh_case_quotes(case: str) -> None:
	"""When a case is lost or reopened, its quotes follow."""
	for name in frappe.get_all("Quotation", {"sp_case": case, "docstatus": ("<", CANCELLED)}, pluck="name"):
		refresh_status(name)


def expire_quotes() -> None:
	"""Daily: sent versions past Valid Till become Expired (SP-170 adds Needs repricing)."""
	for name in frappe.get_all(
		"Quotation",
		{"sp_status": SENT, "docstatus": SUBMITTED, "valid_till": ("<", today())},
		pluck="name",
	):
		refresh_status(name)


def set_cost_and_profit(doc) -> None:
	"""Cost per line from the P1 Cost list when empty; line profit, total cost, profit, margin.

	Only for quotes of a case, so ERPNext's own quotations are left as they are. Who may see
	these fields is SP-35's rule (cost roles only).
	"""
	if not doc.get("sp_case"):
		return
	from smart_power.sp_stock.prices import COST, latest_price

	total_cost = 0.0
	for row in doc.items:
		if not flt(row.get("sp_cost")) and row.item_code:
			price = latest_price(row.item_code, COST, on_date=doc.transaction_date)
			row.sp_cost = flt(price.rate) * flt(row.conversion_factor or 1) if price else 0
		line_cost = flt(row.sp_cost) * flt(row.qty)
		row.sp_line_profit = flt(row.net_amount or row.amount) - line_cost
		total_cost += line_cost
	net = flt(doc.net_total)
	doc.sp_total_cost = total_cost
	doc.sp_profit = net - total_cost
	doc.sp_margin_pct = doc.sp_profit / net * PCT if net else 0


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


def before_cancel(doc, method=None) -> None:
	"""A sent version is never cancelled or amended: the customer can still go back to it.
	Make a new version instead (tech plan section 3 rule 7)."""
	if doc.get("sp_case"):
		frappe.throw(
			_("A sent version cannot be cancelled. Make a new version instead."), title=_("Not allowed")
		)


def after_insert(doc, method=None) -> None:
	"""Version 1 is its own first version; later versions carry it over from new_version."""
	if doc.get("sp_case") and not doc.get("sp_root"):
		doc.db_set("sp_root", doc.name, update_modified=False)


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
	# a new version is always an editable draft (Frappe's copy_doc keeps docstatus under tests)
	doc.docstatus = DocStatus.draft()
	for row in doc.get_all_children():
		row.docstatus = DocStatus.draft()
	doc.sp_previous_version = source.name
	doc.sp_root = source.get("sp_root") or source.name
	doc.sp_option_label = source.get("sp_option_label")
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
		refresh_status(other)
	doc.db_set("sp_is_approved", 1)
	refresh_status(doc.name)
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
	refresh_status(quotation)


def _can_approve(case) -> bool:
	user = frappe.session.user
	if user == "Administrator" or set(APPROVE_ROLES) & set(frappe.get_roles(user)):
		return True
	return user in (case.follow_up_owner, case.quote_creator)
