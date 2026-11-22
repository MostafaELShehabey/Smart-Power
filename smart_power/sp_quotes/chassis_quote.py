"""The chassis calculator in quotes (SP-167; decisions 50 and 77).

A calc (SP-166) linked to a quotation prices that quotation's chassis:

- a station quote (pumps, on-grid …) prices its chassis on the template line ``chassis``. With a
  calc, that line takes the calc's kW as its quantity and the calc's cost per kW; its price is
  the calc's offer (the factory's locked markups, the default) or the line's own markup on the
  calc's cost, by the setting "Chassis Markup in Station Offers". Without a calc the line keeps
  the template's per-kW default.
- a "Chassis only" quote is the calc itself: one line at the calc's offer and cost, and the
  customer PDF prints the calc's lines (the price analysis without the cost) with that total,
  so the PDF total is the analysis total. The quote's discounts and margin range work as usual.

Saving a calc updates its draft quote; a sent version stays frozen (SP-54).
"""

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.sp_quotes.engine import COST_X_MARKUP, INFO, PCT, round_rate, totals

QUOTATION, CALC, SETTINGS = "Quotation", "SP Chassis Calc", "Smart Power Settings"
CHASSIS_LINE = "chassis"  # the template line a station quote prices its chassis on
CHASSIS_ONLY = "System Type-CHASSIS"
LOCKED, LINE_MARKUP = "Factory markup", "Line markup"
CALC_FIELDS = ["name", "factory", "capacity_kw", "total_cost", "total_sale"]


def linked_calc(quotation: str | None):
	if not quotation:
		return None
	return frappe.db.get_value(
		CALC, {"quotation": quotation}, CALC_FIELDS, as_dict=True, order_by="modified desc"
	)


def markup_mode() -> str:
	return frappe.db.get_single_value(SETTINGS, "chassis_station_markup") or LOCKED


def is_chassis_only(doc) -> bool:
	if doc.get("sp_system_type"):
		return doc.sp_system_type == CHASSIS_ONLY
	return bool(
		doc.get("sp_case")
		and frappe.db.exists(
			"SP Case System Type",
			{"parent": doc.sp_case, "parenttype": "SP Case", "system_type": CHASSIS_ONLY},
		)
	)


# --- a station quote's chassis line ---------------------------------------------------------------


def use_calculator(doc, result) -> None:
	"""After the template is priced: the chassis line from the quote's calc, when it has one."""
	calc = linked_calc(None if doc.is_new() else doc.name)
	line = next((row for row in result.lines if row.line_key == CHASSIS_LINE), None)
	kw = flt(calc.capacity_kw) if calc else 0
	if not (calc and line and kw > 0):
		return
	cost = flt(calc.total_cost) / kw
	if markup_mode() == LINE_MARKUP and line.pricing_method == COST_X_MARKUP:
		rounding = frappe.db.get_value(
			"SP Calc Template Line", {"parent": doc.sp_calc_template, "line_key": CHASSIS_LINE}, "rounding"
		)
		rate = round_rate(cost * (1 + flt(line.markup) / PCT), rounding)
	else:  # the factory's locked markups: the calc's own offer
		rate = flt(calc.total_sale) / kw
		line.markup, line.lock_markup = None, 1
	line.update(
		qty=kw, cost=cost, rate=rate, amount=kw * rate, cost_amount=flt(calc.total_cost), is_manual_qty=0
	)
	line.profit = line.amount - line.cost_amount
	result.totals = totals(result.lines, result.inputs)
	result.rule_results.append(
		{
			"line_key": CHASSIS_LINE,
			"level": INFO,
			"message": _("The chassis comes from calculator {0}.").format(calc.name),
		}
	)


# --- a "Chassis only" quote -----------------------------------------------------------------------


def _chassis_only_row(doc, calc) -> None:
	from smart_power.sp_quotes.special_lines import MANUAL, service_item

	doc.set("items", [row for row in doc.items if row.get("sp_line_key") != CHASSIS_LINE])
	doc.append(
		"items",
		{
			"item_code": service_item(MANUAL),
			"item_name": _("Galvanised iron chassis - {0}").format(calc.factory),
			"qty": 1,
			"rate": flt(calc.total_sale),
			"sp_cost": flt(calc.total_cost),
			"sp_line_key": CHASSIS_LINE,
			"sp_lock_markup": 1,
			"sp_line_kind": MANUAL,
		},
	)


def on_calc_update(calc_doc) -> None:
	"""SP Chassis Calc on_update: its draft quote follows."""
	from smart_power.sp_quotes.quote_calc import quote_for_edit, recalculate

	if not calc_doc.quotation or frappe.db.get_value(QUOTATION, calc_doc.quotation, "docstatus") != 0:
		return
	doc = quote_for_edit(calc_doc.quotation)
	if is_chassis_only(doc):
		_chassis_only_row(doc, linked_calc(doc.name))
		doc.save()
	elif doc.get("sp_calc_template"):
		recalculate(doc)


def print_lines(doc) -> list[dict] | None:
	"""A chassis-only quote prints its calc's lines (no cost), in the analysis' order."""
	calc = linked_calc(doc.get("name")) if is_chassis_only(doc) else None
	if not calc:
		return None
	return [
		{
			"description": r.part,
			"uom": _("Nos"),
			"qty": flt(r.qty),
			"rate": flt(r.sale_rate),
			"amount": flt(r.sale_amount),
		}
		for r in frappe.get_all(
			"SP Chassis Line",
			{"parent": calc.name, "parenttype": CALC},
			["part", "qty", "sale_rate", "sale_amount"],
			order_by="idx asc",
		)
	]


@frappe.whitelist()
def from_quote(quotation: str) -> dict:
	"""What a new calc takes from its quote: the customer, the panel and the panel count."""
	doc = frappe.get_doc(QUOTATION, quotation)
	doc.check_permission("read")
	panel = max(
		(
			r
			for r in doc.items
			if r.item_code and flt(frappe.get_cached_value("Item", r.item_code, "sp_watt"))
		),
		key=lambda r: flt(r.qty),
		default=None,
	)
	return {
		"customer_name": doc.customer_name,
		"panel_item": panel.item_code if panel else None,
		"panels": int(flt(panel.qty)) if panel else 0,
		"calc": (linked_calc(quotation) or {}).get("name"),
	}
