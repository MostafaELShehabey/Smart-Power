"""The indicative price (SP-49, IP1): a quick sale price for a walk-in or a caller.

    indicative_form(system_type)                      the inputs the page asks for
    indicative_price(system_type, inputs, tier)       {total_sell, price_per_kw, stale_items, run …}

It runs the same engine and template defaults as a formal quote (SP-55, decision 76): the
published SP Calc Template of the system type, priced with the size (HP or kW) and any input
the template needs that has no default; every other input keeps its default. The locked
lines read BTC, or BTB for a company. Nothing is saved as a quote, and cost never leaves the
server: only the sale total, the price per kW and the stale prices come back.

Each result is kept for a day under a `run` id, so "Make quote request" and "Price check only"
write what the user saw on the case (value, date, specs and who ran it) without trusting the
browser. Results are cached per template version, inputs, tier, day and price version; any
Item Price change moves the price version.
"""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, today

from smart_power.sp_quotes.doctype.sp_calc_template.sp_calc_template import published_template
from smart_power.sp_quotes.engine import WARN, calculate, specs
from smart_power.sp_stock.prices import BTC, TIER_LIST

CASE = "SP Case"
TEMPLATE = "SP Calc Template"
INDIVIDUAL = "Individual"
# the size inputs, by their template key; kW also gives the price per kW
HP, KW = "hp", "kw"
SIZE_KEYS = (HP, KW)
WATTS_PER_KW = 1000  # sp-allow-number: unit conversion, not a business value
CACHE_SECONDS = 3600  # sp-allow-number: cache lifetime, not a business value
RUN_SECONDS = 86400  # sp-allow-number: a day to carry a result into a request, not a business value
PRICE_VERSION_KEY = "sp_indicative_price_version"
CACHE_PREFIX, RUN_PREFIX = "sp_indicative_price", "sp_indicative_run"


@frappe.whitelist()
def indicative_form(system_type: str) -> dict:
	"""The published template of the type and the inputs the page asks for: the size, and the
	inputs it needs that have no default. Every other input keeps the template's default."""
	check_access()
	template = template_for(system_type)
	return {"template": template.name, "inputs": asked_inputs(template)}


@frappe.whitelist()
def indicative_price(system_type: str, inputs: dict | str | None = None, tier: str | None = None) -> dict:
	"""The sale price of a system type at the given size. Cost is never returned."""
	check_access()
	template = template_for(system_type)
	tier = tier if tier in TIER_LIST else INDIVIDUAL
	given = asked_values(template, frappe.parse_json(inputs) if isinstance(inputs, str) else inputs)
	key = cache_key(template.name, given, tier)
	result = frappe.cache.get_value(key)
	if not result:
		result = price(template, given, tier)
		frappe.cache.set_value(key, result, expires_in_sec=CACHE_SECONDS)
	return {**result, "run": remember(system_type, result)}


def price(template, given: dict, tier: str) -> dict:
	calc = calculate(template, given, sale_key=TIER_LIST.get(tier, BTC))
	counted = [line for line in calc.lines if not line.is_optional]
	counted_keys = {line.line_key for line in counted}
	names = {line.line_key: line.item_name for line in calc.lines}
	total = flt(calc.totals.sell)
	kw = flt(calc.inputs.get(KW)) or system_kw(counted)
	stale, incomplete = [], []
	for hit in calc.rule_results:
		if hit.get("level") != WARN or hit.get("line_key") not in counted_keys:
			continue
		if hit.get("stale"):
			stale.append(
				{
					"item_code": hit.get("item_code"),
					"item_name": names.get(hit["line_key"]) or hit.get("item_code"),
					"age_days": hit.get("age_days"),
				}
			)
		elif hit["message"] not in incomplete:
			incomplete.append(hit["message"])
	return {
		"template": calc.template,
		"version": calc.version,
		"tier": tier,
		"inputs": given,
		"total_sell": total,
		"kw": kw or None,
		"price_per_kw": total / kw if kw else None,
		"stale_items": stale,
		"incomplete": incomplete,
		"priced_on": today(),
	}


def system_kw(lines) -> float:
	"""The system's kW from its panels: the lines whose item has a watt rating."""
	watts = sum(flt(line.qty) * flt(specs(line.item_code).get("watt")) for line in lines if line.item_code)
	return watts / WATTS_PER_KW


# --- the template and its inputs --------------------------------------------------------------


def template_for(system_type: str):
	if not system_type:
		frappe.throw(_("Choose the system type first."), frappe.MandatoryError)
	name = published_template(system_type)
	if not name:
		frappe.throw(
			_("{0} has no published calculation template, so it has no indicative price yet.").format(
				frappe.bold(frappe.db.get_value("SP List Value", system_type, "value_ar") or system_type)
			),
			title=_("No template"),
		)
	return frappe.get_cached_doc(TEMPLATE, name)


def asked_inputs(template) -> list[dict]:
	"""The size inputs, then the required inputs with no default, in the template's order."""
	return [
		{
			"input_key": row.input_key,
			"label": row.label,
			"input_type": row.input_type,
			"options": row.options,
			"reqd": 1 if row.input_key in SIZE_KEYS else row.reqd,
			"help": row.help,
		}
		for row in template.inputs
		if row.input_key in SIZE_KEYS or (row.reqd and row.default_value in (None, ""))
	]


def asked_values(template, inputs: dict | None) -> dict:
	"""Only the asked inputs are taken; the size must be above zero."""
	inputs = inputs or {}
	values = {}
	for row in asked_inputs(template):
		value = inputs.get(row["input_key"])
		if value in (None, ""):
			continue
		if row["input_type"] in ("Float", "Int"):
			value = flt(value)
			if value < 0 or (row["input_key"] in SIZE_KEYS and not value):
				frappe.throw(_("{0} must be more than zero.").format(frappe.bold(_(row["label"]))))
		values[row["input_key"]] = value
	return values


# --- cache and runs ---------------------------------------------------------------------------


def cache_key(template: str, given: dict, tier: str) -> str:
	from smart_power.sp_core.services.settings import get_settings

	parts = [template, json.dumps(given, sort_keys=True), tier, today(), price_version()]
	parts.append(str(get_settings().modified))  # brand priority and the formula settings
	digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()
	return f"{CACHE_PREFIX}|{digest}"


def price_version() -> int:
	return int(frappe.cache.get_value(PRICE_VERSION_KEY) or 0)


def prices_changed(doc=None, method=None) -> None:
	"""Item Price on_update / on_trash: cached indicative prices are no longer current."""
	frappe.cache.set_value(PRICE_VERSION_KEY, price_version() + 1)


def remember(system_type: str, result: dict) -> str:
	run = frappe.generate_hash()
	frappe.cache.set_value(
		f"{RUN_PREFIX}|{run}",
		{
			"system_type": system_type,
			"template": result["template"],
			"tier": result["tier"],
			"inputs": result["inputs"],
			"kw": result["kw"],
			"total_sell": result["total_sell"],
			"user": frappe.session.user,
			"at": str(now_datetime()),
		},
		expires_in_sec=RUN_SECONDS,
	)
	return run


def recall(run: str | None) -> dict | None:
	"""The result the user saw (only their own); None if it is unknown or has expired."""
	if not run:
		return None
	data = frappe.cache.get_value(f"{RUN_PREFIX}|{run}")
	if not data or data.get("user") != frappe.session.user:
		frappe.throw(_("This indicative price has expired. Calculate it again."), title=_("Expired"))
	return frappe._dict(data)


def record_on_case(case, run: str | None) -> None:
	"""Write the indicative price the user saw on the case (decision 76): value, date, specs,
	template and who ran it. The quote screen later shows the difference (SP-57)."""
	data = recall(run)
	if not data:
		return
	if data.system_type not in {row.system_type for row in case.system_types}:
		frappe.throw(_("The indicative price was for another system type."))
	case.update(
		{
			"indicative_price": data.total_sell,
			"indicative_on": data.at,
			"indicative_by": data.user,
			"indicative_template": data.template,
			"indicative_specs": {**data.inputs, KW: data.kw, "tier": data.tier},
		}
	)
	case.flags.sp_indicative = True


def check_access() -> None:
	"""The people who take requests (C3) use the indicative price."""
	frappe.has_permission(CASE, "create", throw=True)
