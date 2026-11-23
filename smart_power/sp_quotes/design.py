"""T1 Design tools (SP-65): three calculators beside the quote, and "Push to quote".

    catalogue()                                         the panels and drives with their specs, and
                                                        the off-grid template's factors
    string_check(panel, n, strings, drive, tmin, tmax)  the string's voltages against the drive
    select_pumps(head, flow)                            the pumps whose curve covers the duty
    size_offgrid(loads, factors)                        the needs of a load table
    push(quote, tool, values)                           a result into the quote's design inputs,
                                                        recalculated and saved

The string check (owner's decision 23-11-2026): the string Voc at the minimum temperature stays
under the drive's maximum DC voltage; the string Vmp at the maximum temperature stays at or above
the MPPT minimum, and at the minimum temperature at or below the MPPT maximum. Each voltage moves
with the panel's temperature coefficient (sp_temp_coeff_voc), taken against 25 °C, and the
ambient temperature stands for the cell's. The pump head is typed as the depth plus the losses.
"""

from math import ceil

import frappe
from frappe import _
from frappe.utils import cint, flt

from smart_power.rules.technical import KW_PER_HP
from smart_power.sp_quotes.builder import apply
from smart_power.sp_quotes.indicative import WATTS_PER_KW
from smart_power.sp_quotes.offgrid import load_totals, needs
from smart_power.sp_quotes.quote_calc import loads, quote_for_edit
from smart_power.sp_stock.pump_curve import POINT, covers, head_at

ROLES = ("SP System Designer", "SP Quote Creator", "SP Admin", "System Manager")
TEMPLATE, OFFGRID_KEY = "SP Calc Template", "OFFGRID"
STC_C = 25  # sp-allow-number: the panel's specs are measured at 25 °C
DEFAULT_COEFF = -0.29  # sp-allow-number: the story's Voc coefficient (%/°C) when the panel has none
PERCENT = 100  # sp-allow-number: the coefficient is a percent per degree
VOLT_DIGITS = 1  # sp-allow-number: volts are shown to one decimal
KW_DIGITS = 3  # sp-allow-number: a drive need in kW, to the watt
DRIVES_SHOWN = 3  # sp-allow-number: the smallest drives that fit, beside each pump
STRING, PUMP, OFFGRID = "string", "pump", "offgrid"
# the input a quote's template must take for a tool to push into it
TOOL_INPUT = {STRING: "panels_per_string", PUMP: "required_head_m", OFFGRID: "load_w"}
OFFGRID_FACTORS = (
	"sun_hours",
	"inverter_factor",
	"battery_voltage",
	"battery_efficiency",
	"depth_of_discharge",
	"battery_unit_ah",
	"panel_watt",
	"panels_per_string",
)
PANEL_SPECS = ("sp_watt", "sp_vmp", "sp_voc", "sp_isc", "sp_temp_coeff_voc")
DRIVE_SPECS = ("sp_kw", "sp_mppt_min", "sp_mppt_max", "sp_max_dc_v")


def _allowed() -> None:
	frappe.only_for(ROLES)


def _items(spec: str, fields) -> list:
	return frappe.get_all(
		"Item",
		{"disabled": 0, spec: (">", 0)},
		["name", "item_name", "brand", *fields],
		order_by="item_name asc",
	)


def _offgrid_template() -> str | None:
	return frappe.db.get_value(
		TEMPLATE, {"template_key": OFFGRID_KEY}, "name", order_by="is_published desc, creation desc"
	)


def offgrid_defaults() -> dict:
	template = _offgrid_template()
	if not template:
		return {}
	rows = frappe.get_all(
		"SP Calc Template Input",
		{"parent": template, "parenttype": TEMPLATE, "input_key": ("in", OFFGRID_FACTORS)},
		["input_key", "label", "default_value"],
		order_by="idx asc",
	)
	return {r.input_key: {"label": r.label, "value": flt(r.default_value) or None} for r in rows}


@frappe.whitelist()
def catalogue() -> dict:
	_allowed()
	return {
		"panels": _items("sp_voc", PANEL_SPECS),
		"drives": _items("sp_max_dc_v", DRIVE_SPECS),
		"factors": offgrid_defaults(),
		"default_coeff": DEFAULT_COEFF,
	}


# --- string calculator --------------------------------------------------------------------------


def _need(doc, fields: dict) -> None:
	missing = [label for field, label in fields.items() if not flt(doc.get(field))]
	if missing:
		frappe.throw(
			_("{0} has no {1}. Add it on the item first.").format(
				frappe.bold(doc.item_name or doc.name), ", ".join(missing)
			),
			title=_("Missing specs"),
		)


def _check(key: str, label: str, value: float, limit: float, ok: bool) -> dict:
	return {"key": key, "label": label, "value": flt(value, VOLT_DIGITS), "limit": flt(limit), "ok": ok}


@frappe.whitelist()
def string_check(
	panel: str, n: int | str, strings: int | str, drive: str, tmin: float | str, tmax: float | str
) -> dict:
	"""The string's voltages against the drive, at the two temperatures."""
	_allowed()
	n, strings, tmin, tmax = cint(n), cint(strings), flt(tmin), flt(tmax)
	if n < 1 or strings < 1:
		frappe.throw(_("Panels per string and strings must be at least 1."))
	if tmin > tmax:
		frappe.throw(_("The minimum temperature is above the maximum."))
	p = frappe.get_cached_doc("Item", panel)
	d = frappe.get_cached_doc("Item", drive)
	_need(p, {"sp_voc": _("Voc"), "sp_vmp": _("Vmp")})
	_need(d, {"sp_max_dc_v": _("Max DC Voltage"), "sp_mppt_min": _("MPPT Min"), "sp_mppt_max": _("MPPT Max")})
	coeff = flt(p.get("sp_temp_coeff_voc")) or DEFAULT_COEFF

	def at(volts: float, temp: float) -> float:
		return volts * n * (1 + coeff / PERCENT * (temp - STC_C))

	voc_cold, vmp_cold, vmp_hot = at(flt(p.sp_voc), tmin), at(flt(p.sp_vmp), tmin), at(flt(p.sp_vmp), tmax)
	checks = [
		_check(
			"voc",
			_("String Voc at {0} °C < max DC").format(f"{tmin:g}"),
			voc_cold,
			d.sp_max_dc_v,
			voc_cold < flt(d.sp_max_dc_v),
		),
		_check(
			"vmp_hot",
			_("String Vmp at {0} °C ≥ MPPT min").format(f"{tmax:g}"),
			vmp_hot,
			d.sp_mppt_min,
			vmp_hot >= flt(d.sp_mppt_min),
		),
		_check(
			"vmp_cold",
			_("String Vmp at {0} °C ≤ MPPT max").format(f"{tmin:g}"),
			vmp_cold,
			d.sp_mppt_max,
			vmp_cold <= flt(d.sp_mppt_max),
		),
	]
	return {
		"checks": checks,
		"ok": all(c["ok"] for c in checks),
		"coeff": coeff,
		"panel_watt": flt(p.get("sp_watt")),
		"kwp": flt(p.get("sp_watt")) * n * strings / WATTS_PER_KW,
		"string_isc": flt(p.get("sp_isc")),
		"array_isc": flt(p.get("sp_isc")) * strings,
	}


# --- pump selector ------------------------------------------------------------------------------


def _drives_for(kw: float) -> list[dict]:
	rows = frappe.get_all(
		"Item",
		{"disabled": 0, "sp_max_dc_v": (">", 0), "sp_kw": (">=", flt(kw))},
		["name", "item_name", "sp_kw"],
		order_by="sp_kw asc, item_name asc",
		limit=DRIVES_SHOWN,
	)
	return [{"item": r.name, "item_name": r.item_name, "kw": flt(r.sp_kw)} for r in rows]


@frappe.whitelist()
def select_pumps(head: float | str, flow: float | str) -> dict:
	"""The pumps whose curve covers (head, flow), smallest first, each with the drives that fit."""
	_allowed()
	head, flow = flt(head), flt(flow)
	if head <= 0 or flow <= 0:
		frappe.throw(_("Enter the head and the flow."))
	points = {}
	for row in frappe.get_all(
		POINT, {"parenttype": "Item", "parentfield": "sp_curve_points"}, ["parent", "flow_m3h", "head_m"]
	):
		points.setdefault(row.parent, []).append(row)
	items = {
		i.name: i
		for i in frappe.get_all(
			"Item",
			{"name": ("in", list(points) or [""]), "disabled": 0},
			["name", "item_name", "brand", "sp_hp", "sp_kw"],
		)
	}
	pumps = []
	for code, item in items.items():
		if not covers(points[code], head, flow):
			continue
		kw = flt(item.sp_kw) or flt(item.sp_hp) * KW_PER_HP
		pumps.append(
			{
				"item": code,
				"item_name": item.item_name,
				"brand": item.brand,
				"hp": flt(item.sp_hp),
				"head_at_flow": head_at(points[code], flow),
				"drive_kw": flt(kw, KW_DIGITS),
				"drives": _drives_for(kw),
			}
		)
	pumps.sort(key=lambda p: (p["hp"], p["head_at_flow"], p["item_name"] or ""))
	return {"head": head, "flow": flow, "pumps": pumps, "with_curve": len(items)}


# --- off-grid sizing ----------------------------------------------------------------------------


@frappe.whitelist()
def size_offgrid(loads: list | str, factors: dict | str | None = None) -> dict:
	"""A load table's daily and night energy and peak load, and the panels, inverter and batteries
	they need, with the off-grid template's formulas (SP-172)."""
	_allowed()
	rows = frappe.parse_json(loads) if isinstance(loads, str) else loads
	given = frappe.parse_json(factors) if isinstance(factors, str) else factors or {}
	values = {k: flt(given.get(k)) or flt(v["value"]) for k, v in offgrid_defaults().items()}
	values.update({k: flt(v) for k, v in given.items() if k in OFFGRID_FACTORS and flt(v)})
	missing = [k for k in OFFGRID_FACTORS if not values.get(k)]
	if missing:
		frappe.throw(_("Enter {0}.").format(", ".join(missing)))
	totals = load_totals([frappe._dict(r) for r in rows or []])
	if not totals["load_w"]:
		frappe.throw(_("Add at least one load with its watts."))
	need = needs({**values, **totals})
	per_string = values["panel_watt"] * cint(values["panels_per_string"])
	strings = ceil(need["panel_w"] / per_string) if per_string else 0
	return {
		**totals,
		**need,
		"factors": values,
		"strings": strings,
		"panels": strings * cint(values["panels_per_string"]),
		"batteries": ceil(need["battery_ah"] / values["battery_unit_ah"]),
	}


# --- push to quote ------------------------------------------------------------------------------


def _pushed(tool: str, values: dict) -> dict:
	if tool == STRING:
		result = string_check(
			values.get("panel"),
			values.get("n"),
			values.get("strings"),
			values.get("drive"),
			values.get("tmin"),
			values.get("tmax"),
		)
		if not result["ok"]:
			frappe.throw(_("The string check failed: fix the design before pushing it."))
		return {
			"panel_watt": result["panel_watt"] or None,
			"panels_per_string": cint(values.get("n")),
			"strings": cint(values.get("strings")),
		}
	if tool == PUMP:
		hp = frappe.db.get_value("Item", values.get("pump"), "sp_hp") if values.get("pump") else None
		return {
			"required_head_m": flt(values.get("head")),
			"required_flow_m3h": flt(values.get("flow")),
			"hp": flt(hp) or None,
		}
	if tool == OFFGRID:
		result = size_offgrid(values.get("loads"), values.get("factors"))
		return {
			"load_w": result["load_w"],
			"day_wh": result["day_wh"],
			"night_wh": result["night_wh"],
			**result["factors"],
		}
	return {}


@frappe.whitelist(methods=["POST"])
def push(quote: str, tool: str, values: dict | str) -> dict:
	"""Write a tool's result into the quote's design inputs (Q2 step 2), recalculate and save.
	Only the inputs the quote's template takes are written; the rest are named back."""
	_allowed()
	doc = quote_for_edit(quote)
	if not doc.get("sp_calc_template"):
		frappe.throw(_("This quote has no calculation template."))
	values = frappe.parse_json(values) if isinstance(values, str) else values or {}
	if tool not in TOOL_INPUT:
		frappe.throw(_("Unknown design tool {0}.").format(tool))
	new = {k: v for k, v in _pushed(tool, values).items() if v is not None}
	keys = set(
		frappe.get_all(
			"SP Calc Template Input",
			{"parent": doc.sp_calc_template, "parenttype": TEMPLATE},
			pluck="input_key",
		)
	)
	used = {k: v for k, v in new.items() if k in keys}
	if TOOL_INPUT[tool] not in keys:
		frappe.throw(_("Template {0} is not sized by this tool.").format(frappe.bold(doc.sp_calc_template)))
	inputs = loads(doc.sp_design_inputs)
	inputs.update(used)
	apply(doc, {"inputs": inputs}, saving=True)
	doc.save()
	return {"quote": doc.name, "pushed": sorted(used), "skipped": sorted(set(new) - keys)}
