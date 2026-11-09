"""Commercial rules that run on standard ERPNext documents (S0).

The other R1 rules (margin range, price age, 24h quote, field lock, cash held, technical rules)
register here and in rules/technical.py as their DocTypes and fields land in S1 to S3.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt

from smart_power.rules import BLOCK, Finding, RuleContext, rule
from smart_power.sp_core.setup.role_catalogue import role

PCT = 100


def total_discount_pct(doc) -> float:
	"""Discount on the document total as a percent of the total before the discount."""
	if flt(doc.get("additional_discount_percentage")):
		return flt(doc.additional_discount_percentage)
	discount = flt(doc.get("discount_amount"))
	if not discount:
		return 0.0
	after = doc.grand_total if doc.get("apply_discount_on") == "Grand Total" else doc.net_total
	before = flt(after) + discount
	return discount / before * PCT if before else 0.0


def _discount_raised(doc) -> float | None:
	"""The new discount percent when this save raises it, else None."""
	current = total_discount_pct(doc)
	before = doc.get_doc_before_save() if not doc.is_new() else None
	previous = total_discount_pct(before) if before else 0.0
	return current if current > previous else None


def _user_has(key: str) -> bool:
	return role(key) in frappe.get_roles()


@rule(
	"discount_followup_max",
	doctypes=("Quotation",),
	title="Total discount limit for the follow-up owner",
	description="The follow-up owner can give a discount on the total up to the limit in Smart Power Settings.",
	default_level=BLOCK,
	review_category="Discount",
)
def discount_followup_max(doc, ctx: RuleContext):
	if _user_has("admin") or _user_has("quote_creator") or not _user_has("customer_followup"):
		return None
	limit = ctx.settings.followup_discount_max_pct
	pct = _discount_raised(doc)
	if pct is None or not limit or pct <= flt(limit):
		return None
	return Finding(
		message=_("Discount {0}% is above the follow-up owner's limit of {1}%.").format(
			frappe.format(pct, "Percent"), frappe.format(limit, "Percent")
		),
		suggestion=_("Ask the quote creator to approve a larger discount."),
		amount=flt(doc.get("discount_amount")),
	)


@rule(
	"discount_creator_max",
	doctypes=("Quotation",),
	title="Total discount limit for the quote creator",
	description="The quote creator can approve a discount on the total up to the limit in Smart Power Settings; above it the admin is flagged.",
	review_category="Discount",
)
def discount_creator_max(doc, ctx: RuleContext):
	if _user_has("admin") or not _user_has("quote_creator"):
		return None
	limit = ctx.settings.creator_discount_max_pct
	pct = _discount_raised(doc)
	if pct is None or not limit or pct <= flt(limit):
		return None
	return Finding(
		message=_("Discount {0}% is above the quote creator's limit of {1}%.").format(
			frappe.format(pct, "Percent"), frappe.format(limit, "Percent")
		),
		amount=flt(doc.get("discount_amount")),
		highlight=True,
	)


@rule(
	"quote_validity",
	doctypes=("Quotation",),
	title="Quote validity",
	description="A quote cannot be valid for longer than the maximum validity days in Smart Power Settings (or the default validity when no maximum is set).",
)
def quote_validity(doc, ctx: RuleContext):
	settings = ctx.settings
	max_days = settings.max_validity_days or settings.validity_days
	if not max_days or not doc.get("valid_till") or not doc.get("transaction_date"):
		return None
	days = date_diff(doc.valid_till, doc.transaction_date)
	if days <= max_days:
		return None
	return Finding(
		message=_("The quote is valid for {0} days; the maximum is {1}.").format(days, max_days),
		suggestion=_("Set Valid Till to {0} or earlier.").format(
			frappe.format(frappe.utils.add_days(doc.transaction_date, max_days), "Date")
		),
	)
