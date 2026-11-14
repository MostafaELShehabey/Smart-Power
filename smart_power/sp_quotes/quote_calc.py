"""A quote calculated from its template (SP-55).

    calculate_quote(quotation, inputs, template)   price a draft version from a template
    set_line_override(quotation, line_key, field, value, reason)   change one calculated line

The quote keeps the template version it used (Calculation Template), its design inputs and
the quote creator's changes per line (Line Overrides), so a recalculation gives the same
lines. A quantity typed by hand stays and is marked Manual Qty; the item can be changed; a
markup change needs a reason (SP Edit Reason Log) and is refused on a locked line. Lines with
no item yet are listed in the result, not written; optional lines go to the quote's optional
table, outside its totals (SP-59). Rows added by hand are kept.
Only a draft version is calculated: a sent version is frozen (SP-54).
"""

import json

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.permissions import can_see_cost
from smart_power.sp_core.services.audit import log_edit
from smart_power.sp_quotes.doctype.sp_calc_template.sp_calc_template import LOCKED_BTC, published_template
from smart_power.sp_quotes.engine import INFO, OVERRIDABLE, calculate

QUOTATION, TEMPLATE, CASE = "Quotation", "SP Calc Template", "SP Case"
DRAFT = 0


@frappe.whitelist(methods=["POST"])
def calculate_quote(quotation: str, inputs: dict | str | None = None, template: str | None = None) -> dict:
	"""Price a draft version from a template (default: the one it used, else the published one
	for the case's system type). Given inputs replace the stored design inputs."""
	doc = quote_for_edit(quotation)
	if template and template != doc.sp_calc_template:
		if not frappe.db.get_value(TEMPLATE, template, "is_published"):
			frappe.throw(_("Template {0} is not published.").format(frappe.bold(template)))
		doc.sp_calc_template = template
	doc.sp_calc_template = doc.sp_calc_template or default_template(doc)
	if not doc.sp_calc_template:
		frappe.throw(_("There is no published calculation template for this case's system type."))
	if inputs is not None:
		doc.sp_design_inputs = json.dumps(frappe.parse_json(inputs) or {}, ensure_ascii=False)
	return recalculate(doc)


@frappe.whitelist(methods=["POST"])
def set_line_override(
	quotation: str, line_key: str, field: str, value: str | float | None = None, reason: str | None = None
) -> dict:
	"""Change one calculated line (qty, item_code, markup, rate or cost). An empty value goes
	back to the template's. A markup change needs a reason and is refused on a locked line."""
	doc = quote_for_edit(quotation)
	if not doc.sp_calc_template:
		frappe.throw(_("Calculate the quote from its template first."))
	if field not in OVERRIDABLE:
		frappe.throw(_("{0} cannot be changed here.").format(frappe.bold(field)))
	line = next(
		(r for r in frappe.get_doc(TEMPLATE, doc.sp_calc_template).lines if r.line_key == line_key), None
	)
	if not line:
		frappe.throw(
			_("Line {0} is not in template {1}.").format(frappe.bold(line_key), doc.sp_calc_template)
		)
	overrides = loads(doc.sp_calc_overrides)
	current = overrides.get(line_key) or {}
	if field == "markup":
		if line.lock_markup or line.pricing_method == LOCKED_BTC:
			frappe.throw(
				_("Line {0} is locked: its markup cannot change.").format(frappe.bold(line_key)),
				title=_("Locked line"),
			)
		old = current.get("markup", line.default_markup)
		new = line.default_markup if value in (None, "") else flt(value)
		log_edit(doc, "sp_markup_pct", f"{line_key}: {flt(old):g}", f"{line_key}: {flt(new):g}", reason or "")
	if value in (None, ""):
		current.pop(field, None)
	else:
		current[field] = value if field == "item_code" else flt(value)
	if current:
		overrides[line_key] = current
	else:
		overrides.pop(line_key, None)
	doc.sp_calc_overrides = json.dumps(overrides, ensure_ascii=False)
	return recalculate(doc)


@frappe.whitelist()
def template_for_quote(quotation: str, template: str | None = None) -> dict:
	"""The template Calculate will use, and its inputs, so the dialog can ask for them: the one
	picked, else the one the quote used, else the published one for the case's system type."""
	doc = frappe.get_doc(QUOTATION, quotation)
	doc.check_permission("read")
	if not can_see_cost():
		frappe.throw(_("Only the quote creator and the cost roles price a quote."), frappe.PermissionError)
	name = template or doc.get("sp_calc_template") or default_template(doc)
	if not name:
		frappe.throw(_("There is no published calculation template for this case's system type."))
	inputs = frappe.get_all(
		"SP Calc Template Input",
		filters={"parent": name, "parenttype": TEMPLATE},
		fields=["input_key", "label", "input_type", "options", "default_value", "reqd", "help"],
		order_by="idx asc",
	)
	return {"template": name, "inputs": inputs}


def recalculate(doc) -> dict:
	result = calculate(
		doc.sp_calc_template,
		loads(doc.sp_design_inputs),
		loads(doc.sp_calc_overrides),
		on_date=doc.transaction_date,
	)
	write_lines(doc, result)
	doc.save()
	return result


def write_lines(doc, result) -> None:
	"""Replace the calculated rows; keep the rows added by hand. Optional lines go to the
	optional table (SP-59), outside the quote's totals."""
	manual_rows = [row for row in doc.items if not row.get("sp_line_key")]
	manual_optional = [row for row in doc.get("sp_optional_lines") or [] if not row.get("line_key")]
	doc.set("items", [])
	doc.set("sp_optional_lines", [])
	for line in result.lines:
		if not line.item_code:
			result.rule_results.append(
				{"line_key": line.line_key, "level": INFO, "message": _("Not on the quote: no item yet.")}
			)
			continue
		if line.is_optional:
			doc.append(
				"sp_optional_lines",
				{
					"item_code": line.item_code,
					"qty": line.qty,
					"rate": line.rate,
					"sp_cost": line.cost,
					"line_key": line.line_key,
				},
			)
			continue
		doc.append(
			"items",
			{
				"item_code": line.item_code,
				"qty": line.qty,
				"rate": line.rate,
				"sp_cost": line.cost,
				"sp_line_key": line.line_key,
				"sp_markup_pct": line.markup,
				"sp_is_manual_qty": line.is_manual_qty,
				"sp_lock_markup": line.lock_markup,
			},
		)
	for row in manual_rows:
		doc.append("items", row.as_dict(no_default_fields=True))
	for row in manual_optional:
		doc.append("sp_optional_lines", row.as_dict(no_default_fields=True))


def quote_for_edit(name: str):
	doc = frappe.get_doc(QUOTATION, name)
	doc.check_permission("write")
	if not can_see_cost():
		frappe.throw(_("Only the quote creator and the cost roles price a quote."), frappe.PermissionError)
	if doc.docstatus != DRAFT:
		frappe.throw(_("Only a draft version can be calculated. Make a new version."))
	return doc


def default_template(doc) -> str | None:
	"""The published template for the case's first system type."""
	if not doc.get("sp_case"):
		return None
	system_type = frappe.db.get_value(
		"SP Case System Type", {"parent": doc.sp_case, "parenttype": CASE}, "system_type", order_by="idx asc"
	)
	return published_template(system_type) if system_type else None


def loads(value) -> dict:
	if isinstance(value, dict):
		return value
	return json.loads(value) if value else {}
