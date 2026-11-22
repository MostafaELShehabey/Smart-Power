"""Off-grid sizing (SP-172): the request's load table gives the template its three load inputs,
and the calculation reports the needs it sized the products from.

    load_totals(rows)   {load_w, day_wh, night_wh} from SP Load Line rows (qty, watts, hours)
    needs(values)       the panel watts, inverter kW and battery Ah the loads need
    notes(values)       the needs as notes beside the quote's lines (only for an off-grid template)

The formulas follow the owner's off-grid file (16-9-2026):

    panels    (day Wh + night Wh) / sun hours
    inverter  total load W x inverter factor
    batteries night Wh / (battery efficiency x depth of discharge x battery voltage)

Every factor is a template input with a default, never a constant here. The products round up
(owner's decision 22-11-2026): the template's lines pick complete strings and the smallest
inverter and battery at or above the need, and the quote creator can change any of them.
"""

from frappe import _
from frappe.utils import flt

LOAD_INPUTS = ("load_w", "day_wh", "night_wh")
WATTS_PER_KW = 1000  # sp-allow-number: watts in a kilowatt
SHOWN_DIGITS = 1  # sp-allow-number: the needs are shown to one decimal
KW_DIGITS = 3  # sp-allow-number: the inverter need in kW, to the watt
INFO = "info"


def load_totals(rows) -> dict:
	load_w = day_wh = night_wh = 0.0
	for row in rows or []:
		watts = flt(row.get("qty")) * flt(row.get("watts"))
		load_w += watts
		day_wh += watts * flt(row.get("day_hours"))
		night_wh += watts * flt(row.get("night_hours"))
	return {"load_w": load_w, "day_wh": day_wh, "night_wh": night_wh}


def needs(values: dict) -> dict:
	sun_hours = flt(values.get("sun_hours"))
	battery_divisor = (
		flt(values.get("battery_efficiency"))
		* flt(values.get("depth_of_discharge"))
		* flt(values.get("battery_voltage"))
	)
	return {
		"panel_w": (flt(values.get("day_wh")) + flt(values.get("night_wh"))) / sun_hours
		if sun_hours
		else 0.0,
		"inverter_kw": flt(values.get("load_w")) * flt(values.get("inverter_factor")) / WATTS_PER_KW,
		"battery_ah": flt(values.get("night_wh")) / battery_divisor if battery_divisor else 0.0,
	}


def notes(values: dict) -> list[dict]:
	if not set(LOAD_INPUTS) <= set(values):
		return []
	need = needs(values)
	return [
		{
			"line_key": "panels",
			"level": INFO,
			"message": _("Panels needed: {0} W").format(flt(need["panel_w"], SHOWN_DIGITS)),
		},
		{
			"line_key": "inverter",
			"level": INFO,
			"message": _("Inverter needed: {0} kW").format(flt(need["inverter_kw"], KW_DIGITS)),
		},
		{
			"line_key": "batteries",
			"level": INFO,
			"message": _("Batteries needed: {0} Ah at {1} V").format(
				flt(need["battery_ah"], SHOWN_DIGITS), f"{flt(values.get('battery_voltage')):g}"
			),
		},
	]
