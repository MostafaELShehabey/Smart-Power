"""Q2 Quote Builder (SP-57): the server behind the six-step page. The server is the single source
of truth for every total.

    start(case)                  the case's open draft, or a new one priced from its request
    load(name)                   everything the page shows
    recalc(name, data)           the same, for the page's unsaved values; nothing is saved
    save(name, data, modified)   keeps the values; refused when someone saved since `modified`

`data` is what the page edits: {inputs, overrides, header, hand_lines, merge, reasons}.
Overrides are kept per template line, so a typed quantity survives every recalculation and is
tagged manual. Costs, profit and the summary reach only those who see the quote's internals (its
creator and the admin, SP-35); anyone else who may read the quote gets it at sale prices.
"""

import json

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.utils import add_days, cint, flt, today

from smart_power.permissions import sees_quote_internals
from smart_power.rules import evaluate
from smart_power.rules.sales import QUOTE_SEND_EVENT, margin_check
from smart_power.sp_core.documents import sp_blocks
from smart_power.sp_core.services.audit import log_edit
from smart_power.sp_core.services.settings import get_value
from smart_power.sp_quotes.doctype.sp_calc_template.sp_calc_template import LOCKED_BTC
from smart_power.sp_quotes.engine import COST_X_MARKUP, OVERRIDABLE, calculate
from smart_power.sp_quotes.engine import MANUAL as TYPED_PRICE
from smart_power.sp_quotes.indicative import PANELS_LINE, WATTS_PER_KW
from smart_power.sp_quotes.payment_plans import schedule_of, set_quote_plans
from smart_power.sp_quotes.price_age import set_line_ages
from smart_power.sp_quotes.quote_calc import default_template, loads, quote_for_edit, write_lines
from smart_power.sp_quotes.special_lines import MANUAL, before_validate, service_item
from smart_power.sp_sales.quotation import set_cost_and_profit
from smart_power.sp_stock.consignment import CONTAINER, EMPTY
from smart_power.sp_stock.warehouses import sites_group

QUOTATION, CASE, TEMPLATE = "Quotation", "SP Case", "SP Calc Template"
HEADER_FIELDS = ("valid_till", "sp_scope", "sp_payment_plan", "sp_execution_period")
HAND_FIELDS = ("item_code", "item_name", "qty", "rate", "sp_cost", "sp_line_kind", "sp_merge_group")
# the request's answers that a template input of another name asks for
REQUEST_INPUTS = {"pump_depth": "pump_depth_m", "well_depth": "well_depth_m", "water_level": "water_level_m"}
CANCELLED = DocStatus.cancelled()
COST_PLAN_FIELDS = ("contribution", "contribution_cost", "net_profit", "net_margin_pct")


# --- opening a quote ------------------------------------------------------------------------------


def _company() -> str:
	return (
		frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
		or frappe.get_all("Company", pluck="name", limit=1)[0]
	)


def request_inputs(case, template: str) -> dict:
	"""The template's inputs the request already answers."""
	details = loads(case.request_details)
	keys = frappe.get_all(
		"SP Calc Template Input", {"parent": template, "parenttype": TEMPLATE}, pluck="input_key"
	)
	found = {k: details.get(REQUEST_INPUTS.get(k, k)) for k in keys}
	return {k: v for k, v in found.items() if v not in (None, "")}


def create_draft(case) -> str:
	"""A first draft for the case: its template's lines from the request, or one hand line to
	start from when the system type has no template yet or the request lacks a required input."""
	doc = frappe.get_doc(
		{
			"doctype": QUOTATION,
			"quotation_to": "Customer",
			"party_name": case.customer,
			"company": _company(),
			"order_type": "Sales",
			"transaction_date": today(),
			"sp_case": case.name,
			"sp_quote_creator": case.quote_creator,
		}
	)
	doc.sp_calc_template = default_template(doc)
	if doc.sp_calc_template:
		inputs = request_inputs(case, doc.sp_calc_template)
		doc.sp_design_inputs = json.dumps(inputs, ensure_ascii=False)
		try:
			write_lines(doc, calculate(doc.sp_calc_template, inputs, on_date=doc.transaction_date))
		except frappe.MandatoryError:
			frappe.clear_messages()
	if not doc.items:
		system = case.system_types[0].system_type if case.system_types else None
		label = frappe.db.get_value("SP List Value", system, "value_ar") if system else None
		doc.append(
			"items",
			{"item_code": service_item(MANUAL), "item_name": label or _("Quote line"), "qty": 1, "rate": 0},
		)
	doc.insert()
	return doc.name


@frappe.whitelist(methods=["POST"])
def start(case: str) -> dict:
	"""The case's open draft, or a new one (Q3 "Start the Quote")."""
	doc = frappe.get_doc(CASE, case)
	doc.check_permission("read")
	draft = frappe.db.get_value(
		QUOTATION, {"sp_case": case, "docstatus": 0}, "name", order_by="creation desc"
	)
	return {"quotation": draft or create_draft(doc)}


# --- the values the page edits --------------------------------------------------------------------


def _template_lines(doc) -> dict:
	if not doc.get("sp_calc_template"):
		return {}
	return {r.line_key: r for r in frappe.get_doc(TEMPLATE, doc.sp_calc_template).lines}


def _check_overrides(doc, overrides: dict, reasons: dict, saving: bool) -> None:
	lines, before = _template_lines(doc), loads(doc.sp_calc_overrides)
	for key, values in overrides.items():
		line = lines.get(key)
		if not line:
			frappe.throw(_("Line {0} is not in template {1}.").format(frappe.bold(key), doc.sp_calc_template))
		for field in values:
			if field not in OVERRIDABLE:
				frappe.throw(_("{0} cannot be changed here.").format(frappe.bold(field)))
		old = (before.get(key) or {}).get("markup", line.default_markup)
		new = values.get("markup", line.default_markup)
		if flt(old) == flt(new):
			continue
		if line.lock_markup or line.pricing_method == LOCKED_BTC:
			frappe.throw(
				_("Line {0} is locked: its markup cannot change.").format(frappe.bold(key)),
				title=_("Locked line"),
			)
		if saving:
			log_edit(
				doc, "sp_markup_pct", f"{key}: {flt(old):g}", f"{key}: {flt(new):g}", reasons.get(key) or ""
			)


def _keep_picks(doc, result) -> None:
	"""What the page needs of a calculation beyond the quote's rows: each line's item group, and
	the lines waiting for an item, which are not on the quote until the creator picks one."""
	doc.flags.sp_item_groups = {line.line_key: line.item_group for line in result.lines if line.item_group}
	doc.flags.sp_pricing = {line.line_key: line for line in result.lines}
	doc.flags.sp_pending = [
		{
			"line_key": line.line_key,
			"section": line.section,
			"item_name": line.item_name or line.line_key,
			"item_group": line.item_group,
			"qty": flt(line.qty),
		}
		for line in result.lines
		if line.item_group and not line.item_code and flt(line.qty)
	]


def apply(doc, data: dict, saving: bool = False) -> list:
	"""Put the page's values on the quote and price it, unsaved. Returns the template's notes."""
	data = frappe._dict(data or {})
	for field, value in (data.header or {}).items():
		if field in HEADER_FIELDS:
			doc.set(field, value or None)
	if data.inputs is not None:
		doc.sp_design_inputs = json.dumps(data.inputs, ensure_ascii=False)
	if data.overrides is not None:
		_check_overrides(doc, data.overrides, data.reasons or {}, saving)
		doc.sp_calc_overrides = json.dumps(data.overrides, ensure_ascii=False)
	if data.hand_lines is not None:
		doc.set("items", [r for r in doc.items if r.get("sp_line_key")])
		for row in data.hand_lines:
			doc.append("items", {f: row.get(f) for f in HAND_FIELDS})
	notes = []
	if doc.get("sp_calc_template"):
		result = calculate(
			doc.sp_calc_template,
			loads(doc.sp_design_inputs),
			loads(doc.sp_calc_overrides),
			on_date=doc.transaction_date,
		)
		_keep_picks(doc, result)
		write_lines(doc, result)
		notes = result.rule_results
	for row in doc.items:
		if row.get("sp_line_key") in (data.merge or {}):
			row.sp_merge_group = data.merge[row.sp_line_key] or None
	before_validate(doc)
	doc.set_missing_values(for_validate=True)
	doc.calculate_taxes_and_totals()
	set_cost_and_profit(doc)
	set_line_ages(doc)
	set_quote_plans(doc)
	return notes


# --- what the page shows ------------------------------------------------------------------------


def _plant_kw(doc) -> float:
	inputs = loads(doc.sp_design_inputs)
	panels = next((r for r in doc.items if r.get("sp_line_key") == PANELS_LINE), None)
	return flt(panels.qty) / WATTS_PER_KW if panels else flt(inputs.get("kw"))


def _stock(doc) -> dict:
	"""{item: {company, consignment}} beside each pick: the company's stores (not the goods already
	on a site) and the supplier's consignment containers, which are outside the stock ledger."""
	codes = list({r.item_code for r in doc.items if r.item_code})
	if not codes:
		return {}
	stock = {code: {"company": 0.0, "consignment": 0.0} for code in codes}
	stores = {"company": doc.company, "is_group": 0}
	sites = sites_group(doc.company)
	if sites:
		stores["parent_warehouse"] = ("!=", sites)
	warehouses = frappe.get_all("Warehouse", stores, pluck="name")
	for bin_row in frappe.get_all(
		"Bin",
		{"item_code": ("in", codes), "warehouse": ("in", warehouses)},
		["item_code", "actual_qty"],
	):
		stock[bin_row.item_code]["company"] += flt(bin_row.actual_qty)
	for box in frappe.get_all(
		CONTAINER, {"item": ("in", codes), "status": ("!=", EMPTY)}, ["item", "available_qty"]
	):
		stock[box.item]["consignment"] += flt(box.available_qty)
	return stock


def _line(row, internals: bool, stock: dict | None = None) -> dict:
	line = {
		"name": row.name,
		"line_key": row.get("sp_line_key"),
		"section": row.get("sp_line_section"),
		"item_code": row.item_code,
		"item_name": row.item_name,
		"uom": row.uom,
		"qty": flt(row.qty),
		"rate": flt(row.rate),
		"amount": flt(row.amount),
		"manual": cint(row.get("sp_is_manual_qty")),
		"locked": cint(row.get("sp_lock_markup")),
		"kind": row.get("sp_line_kind"),
		"merge": row.get("sp_merge_group"),
		"price_status": row.get("sp_price_status"),
		"price_age": row.get("sp_price_age_days"),
	}
	if internals:
		cost = flt(row.get("sp_cost"))
		line.update(
			cost=cost,
			profit=flt(row.amount) - cost * flt(row.qty),
			markup=row.get("sp_markup_pct"),
			stock=(stock or {}).get(row.item_code),
		)
	return line


def _inputs(doc) -> list[dict]:
	if not doc.get("sp_calc_template"):
		return []
	values = loads(doc.sp_design_inputs)
	rows = frappe.get_all(
		"SP Calc Template Input",
		{"parent": doc.sp_calc_template, "parenttype": TEMPLATE},
		["input_key", "label", "input_type", "options", "default_value", "reqd", "help"],
		order_by="idx asc",
	)
	return [{**r, "value": values.get(r.input_key, r.default_value)} for r in rows]


def _options(doc) -> list[dict]:
	rows = frappe.get_all(
		QUOTATION,
		{"sp_case": doc.sp_case, "docstatus": ("<", CANCELLED), "sp_is_latest": 1},
		["name", "sp_option_label", "sp_version", "rounded_total", "grand_total", "sp_status"],
		order_by="sp_option_label asc",
	)
	return [
		{
			"name": r.name,
			"label": r.sp_option_label,
			"version": r.sp_version,
			"total": flt(r.rounded_total or r.grand_total),
			"status": r.sp_status,
			"is_this": r.name == doc.name,
		}
		for r in rows
	]


def _plans(doc, internals: bool) -> list[dict]:
	out = []
	for r in doc.get("sp_payment_plans") or []:
		plan = {
			"template": r.template,
			"total": flt(r.plan_total),
			"down": flt(r.down_payment),
			"installments": r.installments,
			"installment": flt(r.installment_amount),
			"cheque": flt(r.cheque_amount),
			"schedule": schedule_of(r),
		}
		if internals:
			plan.update({f: flt(r.get(f)) for f in COST_PLAN_FIELDS})
		out.append(plan)
	return out


def _summary(doc) -> dict:
	sell, kw = flt(doc.net_total), _plant_kw(doc)
	return {
		"cost": flt(doc.sp_total_cost),
		"sell": flt(doc.rounded_total or doc.grand_total),
		"profit": flt(doc.sp_profit),
		"margin": flt(doc.sp_margin_pct),
		"price_per_kw": sell / kw if kw else None,
		"kw": kw,
		"discount": flt(doc.discount_amount),
		"range": margin_check(doc),
	}


def _price_edits(line) -> dict:
	"""How a template line's sell price may change: typed on a manual-price line, through the
	markup on a cost-plus line, and not at all on a locked or list price."""
	method = line.pricing_method if line else None
	return {
		"rate_editable": method == TYPED_PRICE,
		"markup_editable": method == COST_X_MARKUP and not cint(line.lock_markup),
	}


def _notes(doc) -> list:
	"""The template's technical notes for a draft as it stands (its inputs may still be incomplete)."""
	if cint(doc.docstatus) != 0 or not doc.get("sp_calc_template"):
		return []
	try:
		result = calculate(
			doc.sp_calc_template,
			loads(doc.sp_design_inputs),
			loads(doc.sp_calc_overrides),
			on_date=doc.transaction_date,
		)
		_keep_picks(doc, result)
		return result.rule_results
	except frappe.ValidationError:
		frappe.clear_messages()
		return []


def _rules(doc) -> list[dict]:
	"""What the rules would say on sending this draft, at the levels set in the rules screen."""
	if cint(doc.docstatus) != 0:
		return []
	return [
		{"key": h.spec.key, "level": h.level, "message": h.finding.message}
		for h in evaluate(doc, QUOTE_SEND_EVENT)
	]


def payload(doc, notes=None) -> dict:
	internals = sees_quote_internals(doc)
	stock = _stock(doc) if internals else {}
	notes = (notes if notes is not None else _notes(doc)) if internals else []
	groups, pricing = doc.flags.sp_item_groups or {}, doc.flags.sp_pricing or {}
	case = (
		frappe.db.get_value(
			CASE, doc.sp_case, ["customer_name", "location_text", "payment_method", "mobile"], as_dict=True
		)
		or frappe._dict()
	)
	lines = [
		{
			**_line(r, internals, stock),
			"item_group": groups.get(r.get("sp_line_key")),
			**_price_edits(pricing.get(r.get("sp_line_key"))),
		}
		for r in doc.items
		if internals or r.get("sp_line_kind") != "Commission"
	]
	return {
		"header": {
			"name": doc.name,
			"case": doc.sp_case,
			"customer": doc.party_name,
			"customer_name": doc.customer_name or case.customer_name,
			"mobile": case.mobile,
			"tier": frappe.db.get_value("Customer", doc.party_name, "sp_tier"),
			"site": case.location_text,
			"payment_method": case.payment_method,
			"template": doc.get("sp_calc_template"),
			"version": doc.get("sp_version"),
			"option": doc.get("sp_option_label"),
			"status": doc.get("sp_status"),
			"docstatus": cint(doc.docstatus),
			"transaction_date": str(doc.transaction_date),
			"valid_till": str(doc.valid_till) if doc.valid_till else None,
			"sp_scope": doc.get("sp_scope"),
			"sp_payment_plan": doc.get("sp_payment_plan"),
			"sp_execution_period": doc.get("sp_execution_period"),
			"currency": doc.currency,
			"modified": str(doc.modified) if doc.modified else None,
		},
		"can_edit": cint(doc.docstatus) == 0 and internals and bool(doc.has_permission("write")),
		"inputs": _inputs(doc),
		"overrides": loads(doc.get("sp_calc_overrides")),
		"lines": lines,
		"notes": notes,
		"pending": (doc.flags.sp_pending or []) if internals else [],
		"rules": _rules(doc) if internals else [],
		"options": _options(doc),
		"plans": _plans(doc, internals),
		"terms": [str(b) for b in sp_blocks("Quotation", doc)],
		"summary": _summary(doc) if internals else None,
		"total": flt(doc.rounded_total or doc.grand_total),
	}


# --- the page's calls -----------------------------------------------------------------------------


@frappe.whitelist()
def load(name: str) -> dict:
	doc = frappe.get_doc(QUOTATION, name)
	doc.check_permission("read")
	if not doc.get("sp_case"):
		frappe.throw(_("Only a quote of a case opens in the builder."))
	if not doc.valid_till and get_value("validity_days"):
		doc.valid_till = add_days(doc.transaction_date, cint(get_value("validity_days")))
	return payload(doc)


@frappe.whitelist(methods=["POST"])
def recalc(name: str, data: dict | str | None = None) -> dict:
	"""Price the page's values; nothing is saved."""
	doc = quote_for_edit(name)
	notes = apply(doc, frappe.parse_json(data) if isinstance(data, str) else data)
	return payload(doc, notes)


@frappe.whitelist(methods=["POST"])
def save(name: str, data: dict | str | None = None, modified: str | None = None) -> dict:
	"""Keep the page's values. Someone else's newer save is never overwritten."""
	doc = quote_for_edit(name)
	if modified and str(doc.modified) != str(modified):
		frappe.throw(
			_("{0} changed this quote since you opened it. Reload to see their changes.").format(
				frappe.utils.get_fullname(doc.modified_by)
			),
			frappe.TimestampMismatchError,
		)
	notes = apply(doc, frappe.parse_json(data) if isinstance(data, str) else data, saving=True)
	doc.save()
	return payload(doc, notes)
