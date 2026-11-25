"""The chassis calc on the desk (SP-166): the factory's record → the pure engine → the calc.

    factory_dict(name)        a factory's numbers and parts, as the engine reads them
    apply(doc)                SP Chassis Calc validate: geometry, parts, prices and totals
    seed_factories()          Agri Solar and Ali El-Shafei from their approved sheets, once each

Markups live per factory and only the admin changes them (owner, 2026-11-22): a calc takes its
factory's, and anyone else changing it on a calc is refused. Supplier costs are entered by the
admin on the factory; the seed leaves them empty (the repo is public).
"""

import os

import frappe
from frappe import _
from frappe.utils import cint, flt

from smart_power.sp_quotes.chassis import CUT, EPS, ROWS_PER_ARRAY, STANDARD, TIMES, TOTALS, compute

FACTORY, CALC = "SP Chassis Factory", "SP Chassis Calc"
ADMIN_ROLES = ("SP Admin", "System Manager")
SEED_FILE = os.path.join(os.path.dirname(__file__), "chassis_factories.json")
PART_FIELDS = (
	"key",
	"part",
	"group",
	"section",
	"length_m",
	"kg_per_m",
	"unit_weight_kg",
	"qty_formula",
	"basis",
	"unit_cost",
	"price_rule",
	"markup",
	"kg_price_digits",
	"unit_price_digits",
	"unit_rounding",
	"in_iron_weight",
)


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def rail_lengths(text: str) -> list[float]:
	lengths = sorted({flt(x) for x in (text or "").replace("،", ",").split(",") if flt(x) > 0})
	if not lengths:
		frappe.throw(_("Give the holder lengths, e.g. 4, 5, 6."))
	return lengths


def factory_dict(name_or_doc) -> dict:
	doc = frappe.get_doc(FACTORY, name_or_doc) if isinstance(name_or_doc, str) else name_or_doc
	return {
		"panel_gap": flt(doc.panel_gap),
		"min_spacing": flt(doc.min_spacing),
		"max_spacing": flt(doc.max_spacing),
		"design_spacing": flt(doc.design_spacing) or flt(doc.max_spacing),
		"spacing_step": flt(doc.spacing_step),
		"spacing_rounding": doc.spacing_rounding,
		"j_min": flt(doc.j_min),
		"j_max": flt(doc.j_max),
		"j_target": flt(doc.j_target),
		"default_supports": cint(doc.default_supports) or 1,
		"max_supports": cint(doc.max_supports) or 1,
		"rail_label": doc.rail_label,
		"rail_section": doc.rail_section,
		"rail_kg_per_m": flt(doc.rail_kg_per_m),
		"rail_lengths": rail_lengths(doc.rail_lengths),
		"default_rail_mode": doc.default_rail_mode or CUT,
		"rail_lines_per_row": cint(doc.rail_lines_per_row) or ROWS_PER_ARRAY,
		"iron_cost_kg": iron_cost(doc),
		"iron_markup": flt(doc.iron_markup),
		"iron_kg_digits": cint(doc.iron_kg_digits),
		"iron_unit_digits": cint(doc.iron_unit_digits),
		"iron_unit_rounding": doc.iron_unit_rounding,
		"parts": [{f: row.get(f) for f in PART_FIELDS} for row in doc.parts],
	}


def iron_cost(doc) -> float:
	"""The iron item's valuation rate (after landed cost, SP-178), else the cost typed."""
	from smart_power.sp_quotes.engine import valuation_rate

	return (flt(valuation_rate(doc.iron_item)) if doc.get("iron_item") else 0) or flt(doc.iron_cost_kg)


# --- the factory ----------------------------------------------------------------------------------


def validate_factory(doc) -> None:
	"""Each part's formula reads only the totals and the parts above it; weights follow lengths."""
	from smart_power.sp_quotes.formulas import check, check_key

	rail_lengths(doc.rail_lengths)
	if flt(doc.min_spacing) > flt(doc.max_spacing) or flt(doc.j_min) > flt(doc.j_max):
		frappe.throw(_("A minimum is above its maximum."))
	known = set(TOTALS)
	for row in doc.parts:
		where = _("Part {0}").format(row.part)
		key = check_key(row.key, where)
		if key in known:
			frappe.throw(_("{0}: the key {1} is used twice.").format(where, frappe.bold(key)))
		check(row.qty_formula, known, where)
		known.add(key)
		if flt(row.length_m) and flt(row.kg_per_m):
			row.unit_weight_kg = flt(row.length_m) * flt(row.kg_per_m)


# --- the calc -------------------------------------------------------------------------------------


def _rails_text(a: dict) -> str:
	pieces = " + ".join(f"{count}{TIMES}{size:g}" for size, count in a["layout"])
	return f"{a['rail_lines']} {TIMES} ({pieces})" if pieces else ""


def apply(doc) -> None:
	"""Validate an SP Chassis Calc: its factory's rules, then the results onto the form."""
	f = factory_dict(doc.factory)
	before = doc.get_doc_before_save() if not doc.is_new() else None
	markup = flt(doc.iron_markup)
	changed = markup and abs(markup - f["iron_markup"]) > EPS
	if changed and not is_admin() and (not before or flt(before.iron_markup) != markup):
		frappe.throw(_("Only the admin changes the iron markup."), frappe.PermissionError)
	if changed:
		f["iron_markup"] = markup  # the admin priced this calc on purpose
	doc.iron_markup = f["iron_markup"]
	doc.iron_cost_kg = f["iron_cost_kg"]
	doc.rails_mode = doc.rails_mode or f["default_rail_mode"]
	doc.supports_per_stand = cint(doc.supports_per_stand) or f["default_supports"]
	if not 1 <= doc.supports_per_stand <= f["max_supports"]:
		frappe.throw(
			_("Factory {0} takes 1 to {1} supports per stand.").format(doc.factory, f["max_supports"])
		)
	if flt(doc.panel_width_m) <= 0:
		frappe.throw(_("Give the panel width, or a panel item with its size."))
	if doc.quotation and not doc.customer_name:
		doc.customer_name = frappe.db.get_value("Quotation", doc.quotation, "customer_name")
	rows = [r for r in doc.arrays if cint(r.panels) > 0]
	for row in rows:  # a value still equal to the last proposal follows the new one
		if cint(row.stands) and cint(row.stands) == cint(row.proposed_stands):
			row.stands = 0
		if flt(row.spacing) and abs(flt(row.spacing) - flt(row.proposed_spacing)) < EPS:
			row.spacing = 0
	result = compute(
		f,
		{
			"panel_width": flt(doc.panel_width_m),
			"panel_watt": flt(doc.panel_watt),
			"rails_mode": doc.rails_mode if doc.rails_mode in (CUT, STANDARD) else CUT,
			"supports": doc.supports_per_stand,
			"arrays": [r.as_dict() for r in rows],
		},
	)
	for row, a in zip(rows, result["arrays"], strict=True):
		row.update(
			{
				"panels_top": a["panels_top"],
				"panels_bottom": a["panels_bottom"],
				"holder_length": a["holder_length"],
				"proposed_stands": a["proposed_stands"],
				"stands": a["stands"],
				"spacing": a["spacing"],
				"proposed_spacing": a["proposed_spacing"],
				"overhang": a["overhang"],
				"rails": _rails_text(a),
				"review": "\n".join(a["problems"]) or "✓",
			}
		)
	doc.set("lines", [])
	for line in result["lines"]:
		doc.append(
			"lines",
			{
				k: line[k]
				for k in (
					"part",
					"group",
					"section",
					"length_m",
					"unit_weight_kg",
					"qty",
					"unit_cost",
					"cost_amount",
					"kg_sale",
					"sale_rate",
					"sale_amount",
				)
			},
		)
	t = result["totals"]
	doc.update(
		{
			"panels": t["panels"],
			"capacity_kw": t["capacity_kw"],
			"stands": t["stands"],
			"iron_weight_kg": t["iron_weight_kg"],
			"total_cost": t["cost"],
			"total_sale": t["offer"],
			"profit": t["profit"],
			"sale_per_kw": t["sale_per_kw"],
			"review": "\n".join(t["problems"]) or "✓",
		}
	)
	if not priced(doc):
		# priced without its iron: a quote must not take that chassis price (BUG-6)
		problem = _(
			"Factory {0} has no iron cost per kg, so this calc cannot price the chassis. Set the factory's iron item or its iron cost. Until then, quotes keep their own chassis price."
		).format(doc.factory)
		doc.review = problem if doc.review == "✓" else f"{problem}\n{doc.review}"


def priced(calc) -> bool:
	"""A calc with its iron cost, a cost and an offer: only that one prices a quote's chassis.
	Without the iron cost it prices the chassis at nothing, or at its small parts only (BUG-6)."""
	return bool(calc) and flt(calc.iron_cost_kg) > 0 and flt(calc.total_cost) > 0 and flt(calc.total_sale) > 0


# --- the showroom price list ----------------------------------------------------------------------


@frappe.whitelist()
def price_list(factory: str) -> list[dict]:
	"""Each part's sale price for one piece, and each holder length's (SP-166's showroom list)."""
	from smart_power.sp_quotes.chassis import price, rail_lines, unit_weight

	f = factory_dict(factory)
	out = []
	for part in f["parts"]:
		weight = unit_weight(part)
		out.append(
			{
				"part": part["part"],
				"section": part.get("section") or "",
				"length_m": flt(part.get("length_m")),
				"rate": price(part, weight, f)[2],
			}
		)
	arrays = [{"layout": [(size, 1)], "rail_lines": 1} for size in f["rail_lengths"]]
	for line in rail_lines(arrays, f):
		out.append(
			{
				"part": line["part"],
				"section": line["section"],
				"length_m": line["length_m"],
				"rate": line["sale_rate"],
			}
		)
	return out


# --- setup ----------------------------------------------------------------------------------------


def seed_factories() -> list[str]:
	"""Agri Solar and Ali El-Shafei, once each. The admin owns them afterwards."""
	data = frappe.get_file_json(SEED_FILE)
	made = []
	for factory in data["factories"]:
		if frappe.db.exists(FACTORY, factory["factory_name"]):
			continue
		frappe.get_doc({"doctype": FACTORY, **factory}).insert(ignore_permissions=True)
		made.append(factory["factory_name"])
	return made
