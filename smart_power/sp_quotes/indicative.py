"""Indicative price (SP-49, IP1): a quick sale price for a walk-in or a caller.

The price runs the same engine and template as a formal quote (SP-55, decision 76): the
published template of the system type, its defaults, and the few inputs the template needs
(its required ones, e.g. HP and pump depth). Nothing is saved as a quote, and no cost or
profit ever leaves the server.

    indicative_form(system_type)            the template and the inputs to ask for
    indicative_price(system_type, inputs)   {total_sell, plant_kw, price_per_kw, stale[], missing[]}
    record(case, system_type, inputs)       saves the value, date, specs and user on a case
    price_check_only(...)                   closes the enquiry as a Lost case, reason
                                            "Price check only"; the customer is optional

Results are cached per template version, inputs and price version (the newest price change),
so a repeated enquiry answers at once.
"""

import hashlib
import json

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import cstr, flt, now_datetime

from smart_power.sp_core.services.lists import by_code
from smart_power.sp_quotes.doctype.sp_calc_template.sp_calc_template import published_template
from smart_power.sp_quotes.engine import calculate

CASE = "SP Case"
TEMPLATE = "SP Calc Template"
PRICE_CHECK = ("Lost Reason", "PRICE_CHECK_ONLY")
PRICE_CHECK_ACTION = "Price Check Only"
PANELS_LINE = "panels"  # a template's panels line counts its quantity in watts
WATTS_PER_KW = 1000  # sp-allow-number: a unit conversion
CACHE_SECONDS = 3600  # sp-allow-number: an hour; a price change starts a new cache key


def check_access() -> None:
	"""Whoever opens enquiries (cases) may price one."""
	frappe.has_permission(CASE, "create", throw=True)


@frappe.whitelist()
def indicative_form(system_type: str) -> dict:
	"""The published template of the type and its required inputs (the rest take defaults)."""
	check_access()
	template = published_template(system_type)
	if not template:
		return {"template": None, "inputs": []}
	inputs = frappe.get_all(
		"SP Calc Template Input",
		filters={"parent": template, "parenttype": TEMPLATE, "reqd": 1},
		fields=["input_key", "label", "input_type", "options", "help"],
		order_by="idx asc",
	)
	return {"template": template, "inputs": inputs}


@frappe.whitelist()
def indicative_price(system_type: str, inputs: dict | str | None = None) -> dict:
	"""The sale price only: total, plant kW and price per kW, stale prices, lines not priced."""
	check_access()
	inputs = frappe.parse_json(inputs) if isinstance(inputs, str) else dict(inputs or {})
	template = published_template(system_type)
	if not template:
		frappe.throw(_("There is no published calculation template for this system type."))
	key = cache_key(template, inputs)
	cached = frappe.cache.get_value(key)
	if cached:
		return cached
	result = summarize(calculate(template, inputs))
	frappe.cache.set_value(key, result, expires_in_sec=CACHE_SECONDS)
	return result


def cache_key(template: str, inputs: dict) -> str:
	newest = frappe.get_all("Item Price", fields=["modified"], order_by="modified desc", limit=1)
	price_version = cstr(newest[0].modified) if newest else ""
	digest = hashlib.sha1(
		json.dumps([template, inputs, price_version], sort_keys=True, default=str).encode(),
		usedforsecurity=False,
	).hexdigest()
	return f"sp_indicative:{digest}"


def summarize(result) -> dict:
	"""What the enquiry may see: sale amounts and the warnings, never a cost."""
	lines = {line.line_key: line for line in result.lines}
	panels = lines.get(PANELS_LINE)
	plant_kw = flt(panels.qty) / WATTS_PER_KW if panels else flt(result.inputs.get("kw"))
	total = flt(result.totals.sell)
	stale = []
	for rule in result.rule_results:
		line = lines.get(rule.get("line_key"))
		if rule.get("stale"):
			name = (line.item_name if line else None) or rule.get("line_key")
			stale.append({"item_code": line.item_code if line else None, "item_name": name})
	# lines that should carry a sale price and have none yet (no item, or no price): the total
	# is short by them. A missing cost does not change the sale price, so it is not counted.
	missing = [
		line.item_name or line.line_key
		for line in result.lines
		if flt(line.qty) and not flt(line.rate) and not line.is_optional and not line.is_winch_line
	]
	return {
		"template": result.template,
		"version": result.version,
		"inputs": result.inputs,
		"total_sell": total,
		"plant_kw": plant_kw,
		"price_per_kw": total / plant_kw if plant_kw else None,
		"stale": stale,
		"missing": missing,
	}


def record(case, system_type: str, inputs: dict) -> dict:
	"""Write the indicative price on the case (value, date, specs, user, template)."""
	result = indicative_price(system_type, inputs)
	case.update(
		{
			"indicative_price": result["total_sell"],
			"indicative_on": now_datetime(),
			"indicative_by": frappe.session.user,
			"indicative_template": result["template"],
			"indicative_specs": {k: v for k, v in result["inputs"].items() if k in inputs},
		}
	)
	return result


def is_price_check(doc) -> bool:
	return bool(doc.get("lost_reason")) and doc.lost_reason == by_code(*PRICE_CHECK)


@frappe.whitelist(methods=["POST"])
def price_check_only(
	system_type: str,
	inputs: dict | str,
	channel: str,
	mobile: str | None = None,
	customer_name: str | None = None,
	note: str | None = None,
) -> str:
	"""Close the enquiry as lost, reason "Price check only", so it counts in the statistics.
	The mobile (and, for a new one, the name) is optional: without it the case has no customer."""
	from smart_power.sp_sales.customer import find_by_mobile, is_valid_mobile, normalize_mobile
	from smart_power.sp_sales.quote_request import _default_followup_owner

	check_access()
	inputs = frappe.parse_json(inputs) if isinstance(inputs, str) else dict(inputs or {})
	customer = None
	if cstr(mobile).strip():
		number = normalize_mobile(mobile)
		if not is_valid_mobile(number):
			frappe.throw(_("{0} is not a valid Egyptian mobile.").format(frappe.bold(mobile)))
		customer = find_by_mobile(number)
		if not customer:
			if not cstr(customer_name).strip():
				frappe.throw(_("Enter the customer's name: this mobile is new."), frappe.MandatoryError)
			customer = (
				frappe.get_doc(
					{"doctype": "Customer", "customer_name": customer_name.strip(), "sp_mobile": number}
				)
				.insert()
				.name
			)
	case = frappe.get_doc(
		{
			"doctype": CASE,
			"customer": customer,
			"channel": channel,
			"requested_by": frappe.session.user,
			"follow_up_owner": _default_followup_owner() or frappe.session.user,
			"system_types": [{"system_type": system_type}],
			"lost_reason": by_code(*PRICE_CHECK),
			"lost_note": note,
		}
	)
	record(case, system_type, inputs)
	case.insert()
	# opened and closed at once: the workflow's own action, allowed to whoever takes enquiries
	return apply_workflow(case, PRICE_CHECK_ACTION).name
