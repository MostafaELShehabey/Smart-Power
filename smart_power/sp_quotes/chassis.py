"""The chassis calculator (SP-166; decisions 50, 69 and 77): the factory's rules, in pure Python.

A chassis is galvanised iron: stands (each a back leg, a front leg, an inner support and a
slanted beam, set in concrete) carrying four lines of panel holders, with the panels on them in two
rows. Each factory (Agri Solar, Ali El-Shafei) has its own numbers and part formulas, kept on its
SP Chassis Factory record; every number below comes from there, never from this code.

Per array:

    holder length F    (panel width + gap) x panels in the longer row
    stands n           the fewest that keep the spacing ≤ the maximum with the overhang J ≤ its
                       maximum: n = ⌈(F - J max) ÷ s max⌉ + 1 (at least 2); the creator may add
    spacing s          (F - target J) ÷ (n - 1), rounded down to the factory's step, kept between
                       the minimum and the maximum
    overhang J         F - (n - 1) x s, both ends together; checked against its limits
    rails              per line: whole pieces of one length and the rest cut to size, or whole
                       standard lengths (e.g. 3x6 + 3x5 + 1x4) that cover F

The parts' quantities are the factory's formulas over the totals (``stands``, ``arrays``,
``rows``, ``panels``, ``supports``, ``quad_joints``, ``panel_gaps``, ``rail_lines``) and the
earlier parts by their key. Prices follow the factory's sheet: an iron part costs its weight x the
iron cost per kg and sells at the per-kg price (cost x markup, rounded) x its weight, rounded; an
accessory sells at its unit cost x its markup, rounded. The offer is rounded to 10.

    compute(factory, calc) -> {"arrays": [...], "lines": [...], "totals": {...}}
"""

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from frappe import _

from smart_power.sp_quotes.formulas import evaluate

WEIGHT, UNIT_COST = "Weight", "Unit cost"
IRON, CUSTOM = "Iron", "Custom"
ROUND, ROUND_UP = "Round", "Round up"
CUT, STANDARD = "Cut to size", "Standard lengths"
FRAME, HOLDERS, FIXING = "Stand frame", "Panel holders", "Fixing and accessories"
TOTALS = ("stands", "arrays", "rows", "panels", "supports", "quad_joints", "panel_gaps", "rail_lines")
OFFER_STEP = -1  # sp-allow-number: the offer is rounded to 10 (Excel digits -1)
LENGTH_DIGITS = 3  # sp-allow-number: a cut piece's length, to the millimetre
TIMES = "\u00d7"  # the multiplication sign the holder pieces print with
EPS = 1e-9  # sp-allow-number: float tolerance in comparisons
FLOAT_DIGITS = 6  # sp-allow-number: drops binary float noise (micrometres)
GUARD_DIGITS = 9  # sp-allow-number: float noise before Excel rounding
MIN_STANDS = 2  # sp-allow-number: a holder rests on at least two stands
ROWS_PER_ARRAY = 2  # sp-allow-number: an array is two rows of panels
WEIGHT_DIGITS = 3  # sp-allow-number: kilograms to the gram


# --- rounding as in the factories' sheets ----------------------------------------------------------


def excel(value: float, digits: int = 0, mode: str = ROUND) -> float:
	"""Excel's ROUND / ROUNDUP / ROUNDDOWN with digits (negative digits round to tens)."""
	quantum = Decimal(1).scaleb(-int(digits))
	rounding = {ROUND: ROUND_HALF_UP, ROUND_UP: ROUND_CEILING}.get(mode, ROUND_FLOOR)
	return float(Decimal(str(round(value, GUARD_DIGITS))).quantize(quantum, rounding=rounding))


def floor_to(value: float, step: float) -> float:
	"""Excel's FLOOR(value, step)."""
	return round(math.floor(value / step + EPS) * step, FLOAT_DIGITS) if step else value


# --- one array -------------------------------------------------------------------------------------


def holder_length(panels_long_row: int, panel_width: float, gap: float) -> float:
	return round((panel_width + gap) * panels_long_row, FLOAT_DIGITS) if panels_long_row else 0.0


def propose_stands(length: float, max_spacing: float, max_overhang: float) -> int:
	if length <= 0:
		return 0
	return max(MIN_STANDS, math.ceil((length - max_overhang) / max_spacing - EPS) + 1)


def propose_spacing(length: float, stands: int, f: dict) -> float:
	if stands < MIN_STANDS:
		return 0.0
	raw = (length - f["j_target"]) / (stands - 1)
	step = f["spacing_step"]
	if f.get("spacing_rounding") == ROUND and step:  # Ali El-Shafei: to the nearest step
		spacing = round(excel(raw / step) * step, FLOAT_DIGITS)
	else:  # Agri Solar: FLOOR to the step
		spacing = floor_to(raw, step)
	return min(f["max_spacing"], max(f["min_spacing"], spacing))


def parse_layout(text: str) -> list[tuple[float, int]]:
	"""'3x6 + 3x5 + 1x4' (x, * or the times sign) → [(6, 3), (5, 3), (4, 1)]: (length, pieces)."""
	out = []
	for part in (text or "").lower().replace(TIMES, "x").replace("*", "x").split("+"):
		part = part.strip()
		if not part:
			continue
		count, _sep, length = part.partition("x")
		out.append((float(length), int(count)))
	return out


def rail_layout(length: float, mode: str, lengths: list[float], piece: float = 0, manual: str = "") -> list:
	"""The pieces of one holder line: [(length, count)]."""
	if not length:
		return []
	if mode == STANDARD:
		if manual:
			return parse_layout(manual)
		longest = max(lengths)
		whole = int(length / longest + EPS)
		rest = length - whole * longest
		layout = [(longest, whole)] if whole else []
		if rest > EPS:
			cover = min((size for size in lengths if size >= rest - EPS), default=longest)
			layout = _add(layout, cover)
		return layout
	piece = piece or max(lengths)
	whole = int(length / piece + EPS)
	rest = round(length - whole * piece, LENGTH_DIGITS)
	layout = [(piece, whole)] if whole else []
	return [*layout, (rest, 1)] if rest > 0 else layout


def _add(layout: list, size: float) -> list:
	for i, (length, count) in enumerate(layout):
		if length == size:
			return [*layout[:i], (length, count + 1), *layout[i + 1 :]]
	return [*layout, (size, 1)]


def array(row: dict, f: dict, calc: dict) -> dict:
	"""One array's geometry, rails and checks."""
	panels = int(row.get("panels") or 0)
	top = int(row.get("panels_top") or 0) or math.ceil(panels / ROWS_PER_ARRAY)
	bottom = int(row.get("panels_bottom") or 0) or (panels - top)
	if top + bottom != panels:
		bottom = panels - top
	length = holder_length(max(top, bottom), calc["panel_width"], f["panel_gap"])
	proposed = propose_stands(length, f.get("design_spacing") or f["max_spacing"], f["j_max"])
	stands = int(row.get("stands") or 0) or proposed
	proposed_spacing = propose_spacing(length, stands, f)
	spacing = float(row.get("spacing") or 0) or proposed_spacing
	overhang = round(length - (stands - 1) * spacing, FLOAT_DIGITS) if stands else 0.0
	rows = (1 if top else 0) + (1 if bottom else 0)
	lines = f["rail_lines_per_row"] * rows
	layout = rail_layout(
		length,
		calc["rails_mode"],
		f["rail_lengths"],
		float(row.get("rail_piece_length") or 0),
		row.get("rail_layout"),
	)
	pieces = sum(count for _length, count in layout)
	covered = round(sum(size * count for size, count in layout), LENGTH_DIGITS)
	problems = []
	if panels and not (f["j_min"] - EPS <= overhang <= f["j_max"] + EPS):
		problems.append(
			_("the overhang J is {0} m, not between {1} and {2} m").format(
				round(overhang, LENGTH_DIGITS), f["j_min"], f["j_max"]
			)
		)
	if panels and not (f["min_spacing"] - EPS <= spacing <= f["max_spacing"] + EPS):
		problems.append(
			_("the spacing is {0} m, not between {1} and {2} m").format(
				spacing, f["min_spacing"], f["max_spacing"]
			)
		)
	if panels and covered + EPS < length:
		problems.append(_("the rails cover {0} m of {1} m").format(covered, round(length, LENGTH_DIGITS)))
	return {
		"panels": panels,
		"panels_top": top,
		"panels_bottom": bottom,
		"holder_length": length,
		"proposed_stands": proposed,
		"stands": stands,
		"proposed_spacing": proposed_spacing,
		"spacing": spacing,
		"overhang": overhang,
		"rows": rows,
		"rail_lines": lines,
		"layout": layout,
		"quad_joints": max(0, pieces - 1) * lines,
		"panel_gaps": max(0, top - 1) + max(0, bottom - 1),
		"problems": problems,
	}


# --- the parts and their prices --------------------------------------------------------------------


def unit_weight(part: dict) -> float:
	if part.get("length_m") and part.get("kg_per_m"):
		return round(part["length_m"] * part["kg_per_m"], FLOAT_DIGITS)
	return float(part.get("unit_weight_kg") or 0)


def price(part: dict, weight: float, f: dict) -> tuple[float, float, float]:
	"""(unit cost, per-kg sale price, unit sale price) by the factory's sheet."""
	custom = part.get("price_rule") == CUSTOM
	markup = float(part.get("markup") or 0) if custom else f["iron_markup"]
	if part.get("basis", WEIGHT) == WEIGHT:
		cost = weight * f["iron_cost_kg"]
		kg_digits = int(part.get("kg_price_digits") or 0) if custom else f["iron_kg_digits"]
		kg_sale = excel(f["iron_cost_kg"] * markup, kg_digits)
		digits = int(part.get("unit_price_digits") or 0) if custom else f["iron_unit_digits"]
		mode = part.get("unit_rounding") or ROUND if custom else f["iron_unit_rounding"]
		return cost, kg_sale, excel(kg_sale * weight, digits, mode)
	cost = float(part.get("unit_cost") or 0)
	digits = int(part.get("unit_price_digits") or 0)
	return cost, 0.0, excel(cost * markup, digits, part.get("unit_rounding") or ROUND)


def _line(part: dict, qty: float, weight: float, f: dict) -> dict:
	cost, kg_sale, sale = price(part, weight, f)
	return {
		"key": part.get("key"),
		"part": part["part"],
		"group": part.get("group") or FIXING,
		"section": part.get("section") or "",
		"length_m": part.get("length_m") or 0,
		"unit_weight_kg": weight,
		"qty": qty,
		"unit_cost": cost,
		"cost_amount": cost * qty,
		"kg_sale": kg_sale,
		"sale_rate": sale,
		"sale_amount": sale * qty,
		"in_iron_weight": bool(part.get("in_iron_weight")),
	}


def rail_lines(arrays: list[dict], f: dict) -> list[dict]:
	"""The panel holders, one line per length, priced like iron."""
	counts: dict[float, int] = {}
	for a in arrays:
		for size, count in a["layout"]:
			counts[size] = counts.get(size, 0) + count * a["rail_lines"]
	label = f.get("rail_label") or _("Panel holder")
	out = []
	for size in sorted(counts, reverse=True):
		part = {
			"key": f"rail_{size:g}".replace(".", "_"),
			"part": f"{label} {size:g} م",
			"group": HOLDERS,
			"section": f.get("rail_section") or "",
			"length_m": size,
			"kg_per_m": f["rail_kg_per_m"],
			"basis": WEIGHT,
			"price_rule": IRON,
			"in_iron_weight": 1,
		}
		out.append(_line(part, counts[size], unit_weight(part), f))
	return out


def compute(f: dict, calc: dict) -> dict:
	"""Everything a calc shows, from the factory's record and the calc's inputs."""
	arrays = [array(row, f, calc) for row in calc.get("arrays") or [] if int(row.get("panels") or 0)]
	totals = {
		key: sum(a[key] for a in arrays)
		for key in ("stands", "rows", "panels", "quad_joints", "panel_gaps", "rail_lines")
	}
	totals.update(arrays=len(arrays), supports=int(calc.get("supports") or f.get("default_supports") or 1))
	names = dict(totals)
	lines = []
	frame = [p for p in f["parts"] if (p.get("group") or FIXING) == FRAME]
	others = [p for p in f["parts"] if (p.get("group") or FIXING) != FRAME]
	for part in frame:
		lines.append(_part_line(part, names, f))
	lines += rail_lines(arrays, f)
	for part in others:
		lines.append(_part_line(part, names, f))
	lines = [line for line in lines if line["qty"]]
	cost = sum(line["cost_amount"] for line in lines)
	sale = sum(line["sale_amount"] for line in lines)
	offer = excel(sale, OFFER_STEP)
	kw = totals["panels"] * float(calc.get("panel_watt") or 0) / 1000  # sp-allow-number: watts in a kW
	totals.update(
		cost=cost,
		sale=sale,
		offer=offer,
		profit=offer - cost,
		capacity_kw=kw,
		sale_per_kw=round(offer / kw) if kw else 0,
		iron_weight_kg=round(
			sum(line["unit_weight_kg"] * line["qty"] for line in lines if line["in_iron_weight"]),
			WEIGHT_DIGITS,
		),
		problems=[f"{_('Array')} {i}: {p}" for i, a in enumerate(arrays, start=1) for p in a["problems"]],
	)
	return {"arrays": arrays, "lines": lines, "totals": totals}


def _part_line(part: dict, names: dict, f: dict) -> dict:
	where = _("Part {0}").format(part["part"])
	qty = evaluate(part["qty_formula"], names, where)
	if part.get("key"):
		names[part["key"]] = qty
	return _line(part, qty, unit_weight(part), f)
