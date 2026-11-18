"""Sales rules (SP-48 and on)."""

from frappe import _

from smart_power.rules import BLOCK, WARN, Finding, RuleContext, rule
from smart_power.sp_sales.quote_clock import OVERDUE, clock, due_hours

# The quote clock is checked by an hourly job (sp_sales.quote_alerts), not on save.
QUOTE_CLOCK_EVENT = "quote_clock"


@rule(
	"quote_24h",
	doctypes=("SP Case",),
	events=(QUOTE_CLOCK_EVENT,),
	category="Commercial",
	default_level=WARN,
	never_block=True,
	title="Quote within 24 hours",
	description="A quote request should get its quote within Quote Due Within hours (Smart Power "
	"Settings). After that it is listed for the admin and its quote creator is reminded. A warning, "
	"never a block (decision 70).",
	review_category="Rule Warning",
)
def quote_24h(doc, ctx: RuleContext):
	now = clock(doc)
	if now["state"] != OVERDUE:
		return None
	return Finding(
		message=_("No quote sent {0} hours after the request (due within {1} hours).").format(
			now["hours"], due_hours()
		),
		suggestion=_("Prepare and send the quote, or hand the request to another quote creator."),
		highlight=True,
	)


# Checked when a quote version is sent (sp_quotes.quote_send), not on every save.
QUOTE_SEND_EVENT = "quote_send"


def _offer_type(doc) -> str | None:
	import frappe

	if not doc.get("sp_case"):
		return None
	return frappe.db.get_value(
		"SP Case System Type",
		{"parent": doc.sp_case, "parenttype": "SP Case"},
		"system_type",
		order_by="idx asc",
	)


DEFAULT_SCOPE = "Supply and install"


def margin_check(doc) -> dict | None:
	"""The quote's margin against the range of its offer type and scope (SP-63):
	{"margin", "min", "max", "in_range"}, or None when no range applies."""
	from frappe.utils import flt

	from smart_power.sp_core.services.settings import margin_range

	limits = margin_range(_offer_type(doc), doc.get("sp_scope") or DEFAULT_SCOPE)
	if not limits or not (flt(limits.min_pct) or flt(limits.max_pct)):
		return None
	margin = flt(doc.get("sp_margin_pct"))
	low, high = flt(limits.min_pct), flt(limits.max_pct)
	return {
		"margin": round(margin, 1),
		"min": low,
		"max": high,
		"in_range": (not low or margin >= low) and (not high or margin <= high),
	}


@rule(
	"quote_margin_range",
	doctypes=("Quotation",),
	events=(QUOTE_SEND_EVENT,),
	category="Commercial",
	default_level=WARN,
	never_block=True,
	title="Quote margin within its range",
	description="When a quote is sent, its margin should sit inside the range set for its offer type "
	"and project scope (Smart Power Settings > Margin Ranges). Outside it, the quote is listed for the "
	"admin. It never stops a send (decision 58).",
	review_category="Margin",
)
def quote_margin_range(doc, ctx: RuleContext):
	check = margin_check(doc)
	if not check or check["in_range"]:
		return None
	return Finding(
		message=_("Margin {0}% is outside the range {1}% to {2}% for this offer type.").format(
			check["margin"], check["min"], check["max"]
		),
		suggestion=_("Check the prices and the discount before the next version."),
		highlight=True,
	)


# Checked when a version that needs repricing is approved (sp_quotes.repricing), not on every save.
QUOTE_APPROVE_EVENT = "quote_approve"
OLD_PRICE_RULE = "quote_old_price_approval"


@rule(
	OLD_PRICE_RULE,
	doctypes=("Quotation",),
	events=(QUOTE_APPROVE_EVENT,),
	category="Commercial",
	default_level=BLOCK,
	title="Approving a version at its old prices",
	description="A sent version whose prices changed or that expired before the deposit needs repricing. "
	"Block forces a new version at today's prices. Warn lets the admin honor the old price with a reason, "
	"listed for review. Off lets the version be approved.",
	review_category="Rule Warning",
)
def quote_old_price_approval(doc, ctx: RuleContext):
	if not doc.get("sp_needs_repricing"):
		return None
	return Finding(
		message=_("This version needs repricing: {0}").format(
			doc.get("sp_repricing_note") or _("prices changed")
		),
		suggestion=_("Make a new version at today's prices."),
		highlight=True,
	)


def margin_onload(doc, method=None) -> None:
	"""Quotation onload: the margin chip (in range / out of range) for whoever sees the quote's
	cost (its creator, the admin); the follow-up roles never see the margin."""
	from smart_power.permissions import sees_quote_internals

	if not doc.get("sp_case") or not sees_quote_internals(doc):
		return
	check = margin_check(doc)
	if check:
		doc.set_onload("sp_margin_check", check)


PRICE_AGE_RULE = "quote_price_age"


@rule(
	PRICE_AGE_RULE,
	doctypes=("Quotation",),
	events=(QUOTE_SEND_EVENT,),
	category="Commercial",
	default_level=WARN,
	never_block=True,
	title="Stale prices on a quote",
	description="When a quote is sent, a line whose price is older than its price category allows is "
	"checked at the category's level (Price Categories): Warn asks for a reason, listed for the admin; "
	"Block stops the send until the price is updated; Off is no check.",
	review_category="Rule Warning",
)
def quote_price_age(doc, ctx: RuleContext):
	from smart_power.sp_quotes.price_age import describe, stale_lines

	lines = stale_lines(doc)
	if not lines:
		return None
	return Finding(
		message=_("Stale prices: {0}").format(describe(lines)),
		suggestion=_("Update the prices in the price list, then make a new version."),
		highlight=True,
		data={"lines": lines},
	)


def price_age_hit(doc):
	"""The stale-price hit for a quote about to be sent, or None (also when the rule is Off)."""
	from smart_power.rules import evaluate

	return next((h for h in evaluate(doc, QUOTE_SEND_EVENT) if h.spec.key == PRICE_AGE_RULE), None)


@rule(
	"quote_plan_margin",
	doctypes=("Quotation",),
	events=(QUOTE_SEND_EVENT,),
	category="Commercial",
	default_level=WARN,
	never_block=True,
	title="Net margin of the installment plans",
	description="When a quote is sent, each installment plan's net margin after financing (the company "
	"contribution's cost of money taken off) should not fall below the bottom of the offer type's margin "
	"range. Below it, the quote is listed for the admin; it never stops a send.",
	review_category="Margin",
)
def quote_plan_margin(doc, ctx: RuleContext):
	from frappe.utils import flt

	check = margin_check(doc)
	if not check or not check["min"]:
		return None
	low = [r for r in doc.get("sp_payment_plans") or [] if flt(r.net_margin_pct) < check["min"]]
	if not low:
		return None
	return Finding(
		message=_("Net margin after financing below {0}%: {1}").format(
			check["min"], ", ".join(f"{r.template} ({round(flt(r.net_margin_pct), 1)}%)" for r in low)
		),
		suggestion=_("Check the plan's multiplier and service, or the cash price."),
		highlight=True,
	)
