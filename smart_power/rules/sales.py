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


@rule(
	"quote_margin_range",
	doctypes=("Quotation",),
	events=(QUOTE_SEND_EVENT,),
	category="Commercial",
	default_level=WARN,
	never_block=True,
	title="Quote margin within its range",
	description="When a quote is sent, its margin should sit inside the range set for its offer type "
	"(Smart Power Settings > Margin Ranges). Outside it, the quote is listed for the admin. It never "
	"stops a send (decision 58).",
	review_category="Margin",
)
def quote_margin_range(doc, ctx: RuleContext):
	from frappe.utils import flt

	from smart_power.sp_core.services.settings import margin_range

	limits = margin_range(_offer_type(doc), None)
	if not limits or not (flt(limits.min_pct) or flt(limits.max_pct)):
		return None
	margin = flt(doc.get("sp_margin_pct"))
	low, high = flt(limits.min_pct), flt(limits.max_pct)
	if (not low or margin >= low) and (not high or margin <= high):
		return None
	return Finding(
		message=_("Margin {0}% is outside the range {1}% to {2}% for this offer type.").format(
			round(margin, 1), low, high
		),
		suggestion=_("Check the prices and the discount before the next version."),
		highlight=True,
	)
