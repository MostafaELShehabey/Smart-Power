"""The calculation engine (SP-55): a template plus inputs gives priced lines and totals.

    calculate(template, inputs, overrides) -> {template, version, inputs, lines, totals, rule_results}

For each template line, in order:

1. the item: the override, else the selection rule (Manual: the default item; First in stock:
   the first item of the group with stock; Brand priority: the top-priority brand's smallest
   item whose capacity spec covers the need), else the default item;
2. the quantity: the override (kept as manual), else the line's formula;
3. the unit cost: P1 price, the valuation rate (after landed cost), the line's default
   (per kW or manual), or the line's cost formula (SP-56, e.g. an allowance that is a share
   of another line);
4. the unit price: cost x markup, the locked BTC price, the cost (pass-through), the fixed list
   price, or the line's manual price; then the line's rounding.

Optional lines are listed but stay out of the totals (SP-59). Problems that do not stop the
calculation (no price, a stale price, no item for the rule) come back as rule results.
Nothing is saved, and every number comes from the template or the price list.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, date_diff, flt, getdate, today
from frappe.utils.nestedset import get_descendants_of

from smart_power.sp_core.services.settings import brand_priority, get_settings
from smart_power.sp_quotes import formulas
from smart_power.sp_stock.prices import BTC, COST, LIST, STALE, age_status, category_of, latest_price

TEMPLATE = "SP Calc Template"
PCT = 100
# selection rules, cost sources and pricing methods (the template's Select options)
MANUAL, FIRST_IN_STOCK, BRAND_PRIORITY = "Manual", "First in stock", "Brand priority"
P1_COST, VALUATION, PER_KW, COST_FORMULA = "P1 price", "Valuation rate", "Per-kW default", "Formula"
COST_X_MARKUP, LOCKED_BTC, PASS_THROUGH, FIXED_LIST = (
	"Cost x Markup",
	"Locked BTC price",
	"Pass-through",
	"Fixed list price",
)
# item specs a formula can read as item.<name> (custom fields sp_<name> on Item, SP-29)
SPECS = ("hp", "kw", "watt", "battery_ah", "vmp", "voc", "imp", "isc", "max_dc_v", "mppt_min", "mppt_max")
SPECS += ("head_m", "flow_m3h")
WARN, INFO = "warn", "info"
OVERRIDABLE = ("qty", "item_code", "markup", "rate", "cost")


def calculate(template, inputs: dict | None = None, overrides: dict | None = None, on_date=None) -> dict:
	"""Price a template. overrides: {line_key: {qty, item_code, markup, rate, cost}}."""
	doc = template if isinstance(template, Document) else frappe.get_doc(TEMPLATE, template)
	on_date = getdate(on_date or today())
	overrides = overrides or {}
	values = resolve_inputs(doc, inputs or {})
	settings = settings_namespace()
	results, lines, refs = [], [], {}

	for row in doc.lines:
		where = _("Line {0}").format(row.line_key)
		override = overrides.get(row.line_key) or {}
		check_override(row, override, where)
		namespace = {**values, **refs, formulas.SETTINGS: settings}

		item_code = override.get("item_code") or select_item(row, namespace, where, results)
		item = specs(item_code)
		manual_qty = "qty" in override
		qty = (
			flt(override["qty"])
			if manual_qty
			else formulas.evaluate(row.qty_formula or "1", {**namespace, formulas.ITEM: item}, where)
		)
		cost, cost_date = unit_cost(
			row, item_code, override, on_date, results, {**namespace, formulas.ITEM: item}
		)
		markup = flt(override["markup"]) if "markup" in override else flt(row.default_markup)
		rate, rate_date = unit_rate(row, item_code, cost, markup, override, on_date, results)
		rate = round_rate(rate, row.rounding)
		check_age(row, item_code, (cost_date, rate_date), on_date, results)

		line = frappe._dict(
			line_key=row.line_key,
			section=row.section,
			item_group=row.item_group,
			item_code=item_code,
			item_name=item.get("item_name") or row.description,
			uom=item.get("stock_uom"),
			qty=qty,
			cost=cost,
			rate=rate,
			markup=markup if row.pricing_method == COST_X_MARKUP else None,
			amount=qty * rate,
			cost_amount=qty * cost,
			pricing_method=row.pricing_method,
			lock_markup=cint(row.lock_markup),
			is_manual_qty=cint(manual_qty),
			is_optional=cint(row.is_optional),
			is_hidden=cint(row.is_hidden),
			is_winch_line=cint(row.is_winch_line),
			print_group=row.print_group,
		)
		line.profit = line.amount - line.cost_amount
		lines.append(line)
		refs[row.line_key] = frappe._dict(
			qty=qty, cost=cost, rate=rate, amount=line.amount, cost_amount=line.cost_amount, item=item
		)

	return frappe._dict(
		template=doc.name,
		version=doc.version,
		inputs=values,
		lines=lines,
		totals=totals(lines, values),
		rule_results=results,
	)


# --- inputs -----------------------------------------------------------------------------------


def resolve_inputs(doc, given: dict) -> dict:
	"""Every template input with its value: given, else its default; typed; required ones checked."""
	values = {}
	for row in doc.inputs:
		value = given.get(row.input_key)
		if value in (None, ""):
			value = row.default_value
		if value in (None, ""):
			if cint(row.reqd):
				frappe.throw(_("{0} is required.").format(frappe.bold(row.label)), frappe.MandatoryError)
			value = None
		values[row.input_key] = typed(row, value)
	return values


def typed(row, value):
	if row.input_type == "Float":
		return flt(value)
	if row.input_type in ("Int", "Check"):
		return cint(value)
	if row.input_type == "Select" and value not in (None, ""):
		options = [o.strip() for o in (row.options or "").split("\n") if o.strip()]
		if value not in options:
			frappe.throw(_("{0}: {1} is not one of the options.").format(row.label, frappe.bold(value)))
	return value


def settings_namespace() -> frappe._dict:
	"""The numbers in Smart Power Settings, for formulas (settings.<field>)."""
	doc = get_settings()
	numeric = {"Int", "Float", "Currency", "Percent"}
	return frappe._dict(
		{f.fieldname: doc.get(f.fieldname) for f in doc.meta.fields if f.fieldtype in numeric}
	)


# --- the item ---------------------------------------------------------------------------------


def specs(item_code: str | None) -> frappe._dict:
	"""The item's specs for formulas (item.hp, item.watt …), plus its name and unit."""
	if not item_code:
		return frappe._dict()
	fields = ["item_name", "stock_uom", "brand", "item_group"] + [f"sp_{s}" for s in SPECS]
	row = frappe.get_cached_value("Item", item_code, fields, as_dict=True)
	if not row:
		frappe.throw(_("Item {0} does not exist.").format(frappe.bold(item_code)))
	data = frappe._dict(item_code=item_code)
	for key, value in row.items():
		data[key.removeprefix("sp_")] = value
	return data


def select_item(row, namespace: dict, where: str, results: list) -> str | None:
	if row.selection_rule == FIRST_IN_STOCK:
		picked = first_in_stock(row.item_group)
	elif row.selection_rule == BRAND_PRIORITY:
		need = formulas.evaluate(row.need_formula, namespace, where)
		picked = by_brand_priority(row.item_group, row.capacity_field, need)
		if not picked:
			results.append(
				rule(
					row,
					WARN,
					_("No item in {0} covers {1}.").format(
						row.item_group, f"{row.capacity_field} ≥ {need:g}"
					),
				)
			)
	else:
		return row.item_code
	if not picked and row.item_code:
		return row.item_code
	return picked


def group_items(item_group: str, fields: list[str] | None = None) -> list:
	groups = [item_group, *get_descendants_of("Item Group", item_group)]
	return frappe.get_all(
		"Item",
		filters={"item_group": ("in", groups), "disabled": 0},
		fields=["name", *(fields or [])],
		order_by="name asc",
	)


def first_in_stock(item_group: str) -> str | None:
	items = [i.name for i in group_items(item_group)]
	if not items:
		return None
	in_stock = set(
		frappe.get_all("Bin", filters={"item_code": ("in", items), "actual_qty": (">", 0)}, pluck="item_code")
	)
	return next((i for i in items if i in in_stock), None)


def by_brand_priority(item_group: str, capacity_field: str, need: float) -> str | None:
	"""The top-priority brand's smallest item that covers the need (brands without a priority
	come last)."""
	field = f"sp_{capacity_field}"
	order = brand_priority(item_group)
	candidates = [
		i
		for i in group_items(item_group, [field, "brand"])
		if i.get(field) is not None and flt(i.get(field)) >= need
	]
	if not candidates:
		return None

	def rank(i):
		priority = order.index(i.brand) if i.brand in order else len(order)
		return (priority, flt(i.get(field)), i.name)

	return min(candidates, key=rank).name


# --- cost and price ---------------------------------------------------------------------------


def unit_cost(row, item_code, override, on_date, results, namespace=None) -> tuple[float, object]:
	if "cost" in override:
		return flt(override["cost"]), None
	if row.cost_source == COST_FORMULA:
		where = _("Line {0}").format(row.line_key)
		return formulas.evaluate(row.cost_formula, namespace or {}, where), None
	if row.cost_source in (PER_KW, MANUAL):
		return flt(row.cost_default), None
	if not item_code:
		results.append(rule(row, WARN, _("No item, so no cost.")))
		return 0.0, None
	if row.cost_source == VALUATION:
		rate = valuation_rate(item_code)
		if not rate:
			results.append(rule(row, WARN, _("{0} has no valuation rate.").format(item_code)))
		return rate, None
	price = latest_price(item_code, COST, on_date=on_date)
	if not price:
		results.append(rule(row, WARN, _("{0} has no P1 cost.").format(item_code)))
		return 0.0, None
	return flt(price.rate), price.date


def valuation_rate(item_code: str) -> float:
	"""The stock's average valuation rate (after landed cost), else the item's own."""
	bins = frappe.get_all(
		"Bin", filters={"item_code": item_code, "actual_qty": (">", 0)}, fields=["actual_qty", "stock_value"]
	)
	qty = sum(flt(b.actual_qty) for b in bins)
	if qty:
		return sum(flt(b.stock_value) for b in bins) / qty
	return flt(frappe.get_cached_value("Item", item_code, "valuation_rate"))


def unit_rate(row, item_code, cost, markup, override, on_date, results) -> tuple[float, object]:
	method = row.pricing_method
	if method == MANUAL:
		return flt(override.get("rate", row.manual_rate)), None
	if method == COST_X_MARKUP:
		return cost * (1 + markup / PCT), None
	if method == PASS_THROUGH:
		return cost, None
	key = BTC if method == LOCKED_BTC else LIST
	if not item_code:
		results.append(rule(row, WARN, _("No item, so no price.")))
		return 0.0, None
	price = latest_price(item_code, key, on_date=on_date)
	if not price:
		results.append(rule(row, WARN, _("{0} has no {1} price.").format(item_code, _(method))))
		return 0.0, None
	return flt(price.rate), price.date


ROUNDING_NUMBER = re.compile(r"\d+")


def round_rate(rate: float, rounding: str | None) -> float:
	"""The line's rounding: "<n> decimals" or "Nearest <n>"."""
	if not rounding:
		return rate
	number = ROUNDING_NUMBER.search(rounding)
	step = cint(number.group()) if number else 0
	if rounding.startswith("Nearest"):
		return formulas.mround(rate, step)
	return round(rate, step)


def check_age(row, item_code, dates, on_date, results) -> None:
	"""A stale cost or price warns (the stale-price rule itself is SP-63)."""
	dates = [d for d in dates if d]
	if not item_code or not dates:
		return
	age = date_diff(on_date, min(dates))
	if age_status(age, category_of(item_code)) == STALE:
		results.append(rule(row, WARN, _("{0}: price is {1} days old.").format(item_code, age), stale=1))


def check_override(row, override: dict, where: str) -> None:
	unknown = set(override) - set(OVERRIDABLE)
	if unknown:
		frappe.throw(_("{0}: {1} cannot be overridden.").format(where, ", ".join(sorted(unknown))))
	if "markup" in override and (cint(row.lock_markup) or row.pricing_method == LOCKED_BTC):
		if flt(override["markup"]) != flt(row.default_markup):
			frappe.throw(_("{0} is locked: its markup cannot change.").format(where), title=_("Locked line"))


def rule(row, level: str, message: str, **extra) -> dict:
	return {"line_key": row.line_key, "level": level, "message": message, **extra}


def totals(lines: list, values: dict) -> frappe._dict:
	counted = [line for line in lines if not line.is_optional]
	cost = sum(line.cost_amount for line in counted)
	sell = sum(line.amount for line in counted)
	result = frappe._dict(
		cost=cost,
		sell=sell,
		profit=sell - cost,
		margin_pct=(sell - cost) / sell * PCT if sell else 0,
		optional_sell=sum(line.amount for line in lines if line.is_optional),
	)
	kw = flt(values.get("kw"))
	if kw:
		result.price_per_kw = sell / kw
	return result
