"""Technical rules on quotes (SP-169, decisions 56 and 57): is this design buildable?

    quote_inverter_motor   the inverter's rated power covers the motor's, in kW after converting HP
    quote_depth_pipe       the pump depth divides by the length of the chosen pipe, or the nearest
                           valid depths are offered

Each has its level in the rules screen. Warn shows on the quote and is listed for the admin when the
quote is sent. Block stops the send until the design is fixed or the admin overrides with a reason.
The chassis spacing and overhang rule comes with the chassis calculator (SP-166).
"""

import math

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.rules import WARN, Finding, RuleContext, rule
from smart_power.rules.sales import QUOTE_SEND_EVENT

INVERTER_RULE, DEPTH_RULE = "quote_inverter_motor", "quote_depth_pipe"
TECHNICAL_RULES = (INVERTER_RULE, DEPTH_RULE)
KW_PER_HP = 0.746  # sp-allow-number: the definition of a horsepower
DIGITS = 2  # sp-allow-number: power and depth as shown on the quote
TOLERANCE = 1e-6  # sp-allow-number: a whole number of pipes, whatever the float says
TEMPLATE = "SP Calc Template"
# the pump template's inputs, as its pipes line reads them; other templates can name theirs in the limits
DEPTH_INPUTS = {
	"depth": "pump_depth",
	"pipe_type": "pipe_type",
	"plastic": "بلاستيك",
	"plastic_length": "plastic_pipe_m",
	"steel_length": "steel_pipe_m",
}


def rated_kw(item_code: str) -> float:
	"""An item's rated power in kW, whichever unit its catalogue row gives."""
	kw, hp = frappe.db.get_value("Item", item_code, ["sp_kw", "sp_hp"]) or (0, 0)
	return flt(kw) or flt(hp) * KW_PER_HP


def _kw(power: float) -> str:
	return f"{flt(power, DIGITS):g}"


def _line(doc, key: str):
	return next((r for r in doc.get("items") or [] if r.get("sp_line_key") == key and r.item_code), None)


@rule(
	INVERTER_RULE,
	doctypes=("Quotation",),
	events=(QUOTE_SEND_EVENT,),
	category="Technical",
	default_level=WARN,
	title="Inverter at least as large as the motor",
	description="The inverter's rated power must cover the motor's, compared in kW (1 HP = 0.746 kW). "
	"Warn shows on the quote and is listed for the admin. Block stops the send until the inverter is "
	"changed or the admin overrides with a reason.",
	review_category="Rule Warning",
)
def quote_inverter_motor(doc, ctx: RuleContext):
	inverter, motor = (
		_line(doc, ctx.limits.get("inverter_line", "inverter")),
		_line(doc, ctx.limits.get("motor_line", "motor")),
	)
	if not inverter or not motor:
		return None
	inverter_kw, motor_kw = rated_kw(inverter.item_code), rated_kw(motor.item_code)
	if not inverter_kw or not motor_kw or inverter_kw >= motor_kw:
		return None
	return Finding(
		message=_("The inverter {0} ({1} kW) is smaller than the motor {2} ({3} kW).").format(
			inverter.item_code, _kw(inverter_kw), motor.item_code, _kw(motor_kw)
		),
		suggestion=_("Choose an inverter of {0} kW or more.").format(_kw(motor_kw)),
		highlight=True,
	)


def nearest_depths(depth: float, length: float) -> list[float]:
	"""The valid depths on each side of a depth, or nothing when it already divides by the length."""
	depth, length = flt(depth), flt(length)
	if depth <= 0 or length <= 0:
		return []
	pipes = depth / length
	if abs(pipes - round(pipes)) < TOLERANCE:
		return []
	lower = math.floor(pipes) * length
	return [flt(d, DIGITS) for d in (lower, lower + length) if d > 0]


def _design_inputs(doc) -> dict | None:
	"""The quote's inputs with the template's defaults, or None while a required one is missing."""
	from smart_power.sp_quotes.engine import resolve_inputs
	from smart_power.sp_quotes.quote_calc import loads

	if not doc.get("sp_calc_template"):
		return None
	try:
		return resolve_inputs(
			frappe.get_cached_doc(TEMPLATE, doc.sp_calc_template), loads(doc.sp_design_inputs)
		)
	except frappe.ValidationError:
		frappe.clear_messages()
		return None


@rule(
	DEPTH_RULE,
	doctypes=("Quotation",),
	events=(QUOTE_SEND_EVENT,),
	category="Technical",
	default_level=WARN,
	title="Pump depth divides by the pipe length",
	description="The pump depth must be a whole number of pipes of the chosen type, otherwise the nearest "
	"valid depths are suggested. Warn shows on the quote and is listed for the admin. Block stops the "
	"send until the depth is fixed or the admin overrides with a reason.",
	review_category="Rule Warning",
)
def quote_depth_pipe(doc, ctx: RuleContext):
	keys = {**DEPTH_INPUTS, **ctx.limits}
	values = _design_inputs(doc)
	if not values or keys["depth"] not in values:
		return None
	plastic = values.get(keys["pipe_type"]) == keys["plastic"]
	length = flt(values.get(keys["plastic_length"] if plastic else keys["steel_length"]))
	depth = flt(values.get(keys["depth"]))
	depths = nearest_depths(depth, length)
	if not depths:
		return None
	return Finding(
		message=_("Pump depth {0} m does not divide by the {1} m pipe length.").format(
			f"{depth:g}", f"{length:g}"
		),
		suggestion=_("Use {0} m.").format(" / ".join(f"{d:g}" for d in depths)),
		highlight=True,
		data={"input": keys["depth"], "depths": depths},
	)


def technical_hits(doc) -> list:
	from smart_power.rules import evaluate

	return [h for h in evaluate(doc, QUOTE_SEND_EVENT) if h.spec.key in TECHNICAL_RULES]


def technical_onload(doc, method=None) -> None:
	"""Quotation onload: a draft's technical findings, for the banner on the form."""
	if not doc.get("sp_case") or doc.docstatus != 0:
		return
	hits = technical_hits(doc)
	if hits:
		doc.set_onload(
			"sp_technical_rules",
			[
				{"level": h.level, "message": f"{h.finding.message} {h.finding.suggestion or ''}".strip()}
				for h in hits
			],
		)
