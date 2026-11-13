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
