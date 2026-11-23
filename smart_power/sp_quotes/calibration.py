"""Calibration (SP-183): are a template's defaults realistic? Each line's estimate, frozen with the
approved quote at the deposit, against what the closed stations really used and cost.

    station_rows(template_key, from_date, to_date)   the closed stations, with each line's
                                                      estimated and actual quantity and cost
    allocate(lines, quote_items, issues, costs)       one station's lines (pure, for the tests)
    summarise(template, stations, min_stations)       per line: averages, deviations, suggestions
    create_draft(template, from_date, to_date)        the next version with the suggested defaults

A line finds its actual by its calibration source (owner's decision 23-11-2026):

    Items used            the items issued to the station's project (Material Issue, from the site
                          log and service tickets): first the line whose quote item is the issued
                          item, then the first line whose item group (or calibration group) it is
    Site labour           the station's site labour cost (SP-96)
    Winch and transport   the station's winch and transport cost (SP-108)

A cost source is shared among its lines by their estimated cost. A station with no actual recorded
for a line (no labour logged, nothing issued) is left out of that line's averages. The suggestion is the current
default times the average of actual ÷ estimated over the stations (owner's decision): the line's
calibrated input for its quantity, and its default unit cost when it has one. Nothing changes a
published version: "Create draft version" makes the next one for the admin to review.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from smart_power.sp_core.services.settings import get_value
from smart_power.sp_stations.costing import actual_cost

TEMPLATE, LINE, STATION = "SP Calc Template", "SP Calc Template Line", "SP Station"
ROLES = ("SP Admin", "System Manager")
ITEMS, LABOUR, WINCH, NONE = "Items used", "Site labour", "Winch and transport", "Not calibrated"
COST_SOURCES = {LABOUR: "labour", WINCH: "winch"}  # → costing.actual_cost's sources
CLOSED = ("Technically closed", "Financially closed")
PERCENT = 100  # sp-allow-number: a ratio as a percent
DIGITS = 2  # sp-allow-number: a suggested default to two decimals
EMPTY = {"est_qty": 0.0, "est_cost": 0.0, "act_qty": 0.0, "act_cost": 0.0}


def allowed() -> None:
	frappe.only_for(ROLES)


def source_of(line) -> str:
	source = line.get("calibration_source")
	if source:
		return source
	# a calibrated input means the line is measured by its items, even before its group is set
	items = line.get("item_group") or line.get("calibration_group") or line.get("calibration_input")
	return ITEMS if items else NONE


# --- one station ----------------------------------------------------------------------------------


def allocate(lines: list, quote_items: list, issues: list, costs: dict) -> dict:
	"""{line_key: {est_qty, est_cost, act_qty, act_cost}} for the lines the station's quote has.

	quote_items: [{line_key, item_code, stock_qty, cost}] with cost per stock unit x qty already
	issues:      [{item_code, item_group, qty, amount}] in stock units
	costs:       {labour, winch} the station's actual cost per source"""
	sources = {row.line_key: source_of(row) for row in lines}
	out, picked = {}, {}
	for q in quote_items:
		key = q.get("line_key")
		if key not in sources or sources[key] == NONE:
			continue
		row = out.setdefault(key, dict(EMPTY))
		row["est_qty"] += flt(q.get("stock_qty"))
		row["est_cost"] += flt(q.get("cost"))
		if q.get("item_code"):
			picked.setdefault(q["item_code"], key)
	groups = {}
	for line in lines:
		group = line.get("calibration_group") or line.get("item_group")
		if line.line_key in out and sources[line.line_key] == ITEMS and group:
			groups.setdefault(group, line.line_key)
	for issue in issues:
		key = picked.get(issue.get("item_code"))
		if not key or sources.get(key) != ITEMS:
			key = groups.get(issue.get("item_group"))
		if key:
			out[key]["act_qty"] += flt(issue.get("qty"))
			out[key]["act_cost"] += flt(issue.get("amount"))
	for source, cost_key in COST_SOURCES.items():
		keys = [k for k in out if sources[k] == source]
		estimated = sum(out[k]["est_cost"] for k in keys)
		for k in keys:
			share = out[k]["est_cost"] / estimated if estimated else 1 / len(keys)
			out[k]["act_cost"] = flt(costs.get(cost_key)) * share
			out[k]["act_qty"] = out[k]["est_qty"]  # a cost source has no quantity of its own
	return out


def _quote_items(quote: str) -> list[dict]:
	return [
		{
			"line_key": r.sp_line_key,
			"item_code": r.item_code,
			"stock_qty": flt(r.stock_qty) or flt(r.qty),
			"cost": flt(r.sp_cost) * flt(r.qty),
		}
		for r in frappe.get_all(
			"Quotation Item",
			{"parent": quote, "parenttype": "Quotation", "sp_line_key": ("is", "set")},
			["sp_line_key", "item_code", "qty", "stock_qty", "sp_cost"],
		)
	]


def _issues(project: str) -> list[dict]:
	return frappe.db.sql(
		"""select sed.item_code, item.item_group, sum(sed.transfer_qty) as qty,
			sum(sed.amount) as amount
		from `tabStock Entry Detail` sed
		join `tabStock Entry` se on se.name = sed.parent
		join `tabItem` item on item.name = sed.item_code
		where se.docstatus = 1 and se.purpose = 'Material Issue'
			and coalesce(sed.project, se.project) = %s
		group by sed.item_code, item.item_group""",
		project,
		as_dict=True,
	)


def _quote_of(sales_order: str | None) -> str | None:
	if not sales_order:
		return None
	return frappe.db.get_value(
		"Sales Order Item", {"parent": sales_order, "prevdoc_docname": ("is", "set")}, "prevdoc_docname"
	)


def station_rows(template_key: str, from_date=None, to_date=None) -> list[dict]:
	"""The stations closed technically in the period whose approved quote used a version of the
	template, each with its lines (allocate)."""
	filters = {"status": ("in", CLOSED), "tech_closed_on": ("is", "set")}
	if from_date and to_date:
		filters["tech_closed_on"] = ("between", (getdate(from_date), getdate(to_date)))
	versions = frappe.get_all(TEMPLATE, {"template_key": template_key}, pluck="name")
	lines = {}
	out = []
	for st in frappe.get_all(
		STATION, filters, ["name", "project", "sales_order", "tech_closed_on"], order_by="tech_closed_on"
	):
		quote = _quote_of(st.sales_order)
		version = frappe.db.get_value("Quotation", quote, "sp_calc_template") if quote else None
		if version not in versions:
			continue
		if version not in lines:
			lines[version] = frappe.get_all(
				LINE,
				{"parent": version, "parenttype": TEMPLATE},
				["line_key", "item_group", "calibration_source", "calibration_group", "calibration_input"],
				order_by="idx",
			)
		costs = {line["source"]: line["amount"] for line in actual_cost(st.name)["lines"]}
		issues = _issues(st.project) if st.project else []
		out.append(
			{
				"station": st.name,
				"closed_on": st.tech_closed_on,
				"lines": allocate(lines[version], _quote_items(quote), issues, costs),
			}
		)
	return out


# --- the template ---------------------------------------------------------------------------------


def _ratio(rows: list, actual: str, estimated: str) -> float | None:
	ratios = [r[actual] / r[estimated] for r in rows if flt(r[estimated])]
	return sum(ratios) / len(ratios) if ratios else None


def _unit_ratio(rows: list) -> float | None:
	"""Actual ÷ estimated cost per unit: what a unit really cost against the estimate."""
	ratios = [
		(r["act_cost"] / r["act_qty"]) / (r["est_cost"] / r["est_qty"])
		for r in rows
		if flt(r["act_qty"]) and flt(r["est_qty"]) and flt(r["est_cost"])
	]
	return sum(ratios) / len(ratios) if ratios else None


def _pct(ratio: float | None) -> float | None:
	return flt((ratio - 1) * PERCENT, DIGITS) if ratio is not None else None


def summarise(template, stations: list, min_stations: int) -> list[dict]:
	"""One row per template line."""
	inputs = {r.input_key: r.default_value for r in template.inputs}
	out = []
	for line in template.lines:
		source = source_of(line)
		used = [s["lines"][line.line_key] for s in stations if line.line_key in s["lines"]]
		# a station with nothing recorded for the line (no labour logged, no issue) is left out:
		# its zero is missing data, not a real cost, and would pull the suggestion down
		actual = "act_qty" if source == ITEMS else "act_cost"
		rows = [r for r in used if flt(r[actual])]
		count, unrecorded = len(rows), len(used) - len(rows)
		qty_ratio = _ratio(rows, "act_qty", "est_qty") if source == ITEMS else None
		cost_ratio = _ratio(rows, "act_cost", "est_cost")
		unit_ratio = _unit_ratio(rows) if source == ITEMS else cost_ratio
		enough = count >= min_stations and count > 0
		current = flt(inputs.get(line.calibration_input)) if line.get("calibration_input") else None
		row = {
			"line_key": line.line_key,
			"description": line.description or line.line_key,
			"source": source,
			"stations": count,
			"est_qty": sum(r["est_qty"] for r in rows) / count if count else None,
			"act_qty": sum(r["act_qty"] for r in rows) / count if count else None,
			"qty_deviation": _pct(qty_ratio),
			"est_cost": sum(r["est_cost"] for r in rows) / count if count else None,
			"act_cost": sum(r["act_cost"] for r in rows) / count if count else None,
			"cost_deviation": _pct(cost_ratio),
			"input": line.get("calibration_input"),
			"input_default": current,
			"suggested_input": flt(current * qty_ratio, DIGITS)
			if enough and current and qty_ratio is not None
			else None,
			"unrecorded": unrecorded,
			"cost_default": flt(line.cost_default) or None,
			"suggested_cost": flt(flt(line.cost_default) * unit_ratio, DIGITS)
			if enough and flt(line.cost_default) and unit_ratio is not None
			else None,
		}
		if source == ITEMS and not (line.item_group or line.calibration_group):
			row["note"] = _("Set the calibration item group on the line.")
		elif count and not enough:
			row["note"] = _("A suggestion needs {0} stations.").format(min_stations)
		if unrecorded:
			left_out = _("{0} stations had no actual recorded and are left out.").format(unrecorded)
			row["note"] = " ".join(n for n in (row.get("note"), left_out) if n)
		out.append(row)
	return out


def min_stations() -> int:
	return int(flt(get_value("calibration_min_stations")) or 1)


def report(template: str, from_date=None, to_date=None) -> dict:
	doc = frappe.get_doc(TEMPLATE, template)
	stations = station_rows(doc.template_key, from_date, to_date)
	return {"stations": stations, "lines": summarise(doc, stations, min_stations())}


@frappe.whitelist(methods=["POST"])
def create_draft(template: str, from_date: str | None = None, to_date: str | None = None) -> str:
	"""The template's next version, unpublished, with the suggested defaults."""
	allowed()
	result = report(template, from_date, to_date)
	inputs = {r["input"]: r["suggested_input"] for r in result["lines"] if r["suggested_input"] is not None}
	costs = {r["line_key"]: r["suggested_cost"] for r in result["lines"] if r["suggested_cost"] is not None}
	if not (inputs or costs):
		frappe.throw(_("No line has a suggestion yet: nothing to put in a new version."))
	name = frappe.get_doc(TEMPLATE, template).new_version()
	draft = frappe.get_doc(TEMPLATE, name)
	changes = []
	for row in draft.inputs:
		if row.input_key in inputs:
			changes.append(f"{row.input_key}: {row.default_value} → {inputs[row.input_key]:g}")
			row.default_value = f"{inputs[row.input_key]:g}"
	for row in draft.lines:
		if row.line_key in costs:
			changes.append(f"{row.line_key}: {flt(row.cost_default):g} → {costs[row.line_key]:g}")
			row.cost_default = costs[row.line_key]
	draft.save()
	draft.add_comment(
		"Info",
		_("Suggested by the calibration report on {0} closed stations: {1}").format(
			len(result["stations"]), "; ".join(changes)
		),
	)
	return name
