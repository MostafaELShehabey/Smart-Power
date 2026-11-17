"""Sales rules (SP-48 and on)."""

from frappe import _

from smart_power.rules import WARN, Finding, RuleContext, rule
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


def margin_onload(doc, method=None) -> None:
	"""Quotation onload: the margin chip (in range / out of range) for whoever sees the quote's
	cost (its creator, the admin); the follow-up roles never see the margin."""
	from smart_power.permissions import sees_quote_internals

	if not doc.get("sp_case") or not sees_quote_internals(doc):
		return
	check = margin_check(doc)
	if check:
		doc.set_onload("sp_margin_check", check)
