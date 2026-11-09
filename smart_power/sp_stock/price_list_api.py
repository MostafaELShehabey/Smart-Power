"""I2 price list screen API (SP-30).

One row per item with its List Price, P1 Cost, BTB and BTC, their dates and the age chip.
Users without cost access (SP-35) get rows without the List Price and P1 Cost keys: the
columns are not rendered and the values never leave the server.

Editing is for users who may write Item Price (pricing managers and the admin). Changing a
price needs a reason; the category's pricing rules then update the prices worked out from it.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, today
from frappe.utils.number_format import NumberFormat

from smart_power.permissions import can_see_cost, strip_cost
from smart_power.sp_stock import prices
from smart_power.sp_stock.prices import BTB, BTC, COST, COST_SIDE, LIST, PRICE_KEYS

# "Stale first" sort order
AGE_ORDER = {
	status: i
	for i, status in enumerate((prices.STALE, prices.AGING, prices.FRESH, prices.NO_LIMIT, prices.NO_PRICE))
}
SEARCH_FIELDS = ("name", "item_name", "sp_name_ar")
DEFAULT_PAGE_LENGTH = 50  # sp-allow-number: rows per page, not a business value


def _parse(value):
	if isinstance(value, str) and value:
		return json.loads(value)
	return value or {}


def _items(filters: dict) -> list[dict]:
	conditions = {"disabled": 0, "has_variants": 0}
	for field in ("item_group", "brand", "sp_price_age_category"):
		if filters.get(field):
			conditions[field] = filters[field]
	or_filters = None
	if filters.get("search"):
		like = f"%{filters['search'].strip()}%"
		or_filters = [[field, "like", like] for field in SEARCH_FIELDS]
	return frappe.get_list(
		"Item",
		filters=conditions,
		or_filters=or_filters,
		fields=[
			"name",
			"item_name",
			"sp_name_ar",
			"item_group",
			"brand",
			"stock_uom",
			"sp_main_supplier",
			"sp_price_age_category",
		],
		order_by="name asc",
		limit_page_length=0,
	)


def _price_rows(item_codes: list[str], on_date) -> dict:
	"""{(item, key): [rows newest first]} for the four lists, one query."""
	lists = {name: key for key, name in prices.price_lists().items() if name}
	if not item_codes or not lists:
		return {}
	rows = frappe.get_all(
		"Item Price",
		filters={"item_code": ("in", item_codes), "price_list": ("in", list(lists))},
		fields=[
			"name",
			"item_code",
			"price_list",
			"price_list_rate",
			"valid_from",
			"valid_upto",
			"supplier",
			"creation",
		],
		order_by="valid_from desc, modified desc",
	)
	out: dict = {}
	for row in rows:
		date = getdate(row.valid_from or row.creation)
		if date > on_date or (row.valid_upto and getdate(row.valid_upto) < on_date):
			continue
		row.date = date
		out.setdefault((row.item_code, lists[row.price_list]), []).append(row)
	return out


def _pick(rows: list | None, supplier: str | None):
	"""The main supplier's newest row, else the newest row."""
	if not rows:
		return None
	if supplier:
		for row in rows:
			if row.supplier == supplier:
				return row
	return rows[0]


def build_row(item: dict, price_rows: dict, on_date, sees_cost: bool) -> dict:
	category = item.sp_price_age_category or frappe.get_cached_value(
		"Item Group", item.item_group, "sp_price_age_category"
	)
	row = {
		"item_code": item.name,
		"item_name": item.item_name,
		"sp_name_ar": item.sp_name_ar,
		"item_group": item.item_group,
		"brand": item.brand,
		"uom": item.stock_uom,
		"category": category,
	}
	visible_keys = PRICE_KEYS if sees_cost else (BTB, BTC)
	dates = []
	for key in PRICE_KEYS:
		picked = _pick(price_rows.get((item.name, key)), item.sp_main_supplier if key in COST_SIDE else None)
		prefix = {LIST: "list_price", COST: "cost", BTB: "btb", BTC: "btc"}[key]
		row[prefix] = picked.price_list_rate if picked else None
		row[f"{prefix}_date"] = picked.date if picked else None
		if key in COST_SIDE:
			supplier_prefix = "list" if key == LIST else "cost"
			row[f"{supplier_prefix}_supplier"] = picked.supplier if picked else None
		if picked and key in visible_keys:
			dates.append(picked.date)
	if sees_cost:
		row["supplier_count"] = len({r.supplier for r in price_rows.get((item.name, COST), []) if r.supplier})
		if row["cost"] and row["btc"]:
			row["margin_pct"] = flt((row["btc"] - row["cost"]) / row["btc"] * prices.PCT, 1)
	age = date_diff(on_date, min(dates)) if dates else None
	row["age_days"] = age
	row["age_status"] = prices.age_status(age, category)
	row["list_date"] = row.pop("list_price_date")
	return strip_cost(row) if not sees_cost else row


@frappe.whitelist()
def get_rows(
	filters: dict | str | None = None, start: int = 0, page_length: int = DEFAULT_PAGE_LENGTH
) -> dict:
	"""The I2 rows for the filters: item_group, brand, sp_price_age_category, search, age."""
	frappe.has_permission("Item", "read", throw=True)
	filters = _parse(filters)
	on_date = getdate(filters.get("date") or today())
	sees_cost = can_see_cost()
	items = _items(filters)
	price_rows = _price_rows([i.name for i in items], on_date)
	rows = [build_row(item, price_rows, on_date, sees_cost) for item in items]
	if filters.get("age_status"):
		rows = [r for r in rows if r["age_status"] == filters["age_status"]]
	if cint(filters.get("stale_first")):
		rows.sort(key=lambda r: (AGE_ORDER.get(r["age_status"], len(AGE_ORDER)), -(r["age_days"] or 0)))
	start, page_length = cint(start), cint(page_length)
	return {
		"rows": rows[start : start + page_length] if page_length else rows[start:],
		"total": len(rows),
		"sees_cost": sees_cost,
		"can_edit": bool(frappe.has_permission("Item Price", "write")),
		"price_lists": prices.price_lists()
		if sees_cost
		else {k: v for k, v in prices.price_lists().items() if k not in COST_SIDE},
	}


def _check_edit(keys) -> None:
	frappe.has_permission("Item Price", "write", throw=True)
	if any(k in COST_SIDE for k in keys) and not can_see_cost():
		frappe.throw(_("You cannot change cost prices."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def update_prices(
	item_code: str,
	values: dict | str,
	reason: str | None = None,
	supplier: str | None = None,
	price_date: str | None = None,
	apply_rules: int = 1,
) -> dict:
	"""Set one or more prices of an item in one call: values = {"list"|"cost"|"btb"|"btc": rate}.

	Changing an existing price needs a reason. Then the category's pricing rules update the
	prices worked out from the ones given (unless apply_rules is 0 or the item has Manual Prices).
	Returns the item's row as the screen shows it, and the prices the rules changed.
	"""
	values = {k: flt(v) for k, v in _parse(values).items() if k in PRICE_KEYS and v not in (None, "")}
	if not values:
		frappe.throw(_("Enter at least one price."))
	_check_edit(values)
	frappe.get_doc("Item", item_code).check_permission("read")
	price_date = getdate(price_date or today())
	for key, rate in values.items():
		prices.set_price(
			item_code,
			key,
			rate,
			supplier=supplier if key in COST_SIDE else None,
			price_date=price_date,
			reason=reason,
		)
	derived = {}
	if cint(apply_rules):
		derived = prices.apply_category_rules(
			item_code,
			reason=reason or _("Pricing rule"),
			price_date=price_date,
			given=values,
		)
	return {"row": get_row(item_code), "derived": strip_cost(derived)}


def get_row(item_code: str) -> dict:
	on_date = getdate(today())
	item = frappe.get_all(
		"Item",
		filters={"name": item_code},
		fields=[
			"name",
			"item_name",
			"sp_name_ar",
			"item_group",
			"brand",
			"stock_uom",
			"sp_main_supplier",
			"sp_price_age_category",
		],
	)[0]
	return build_row(item, _price_rows([item_code], on_date), on_date, can_see_cost())


@frappe.whitelist(methods=["POST"])
def apply_rules(reason: str, item_code: str | None = None, category: str | None = None) -> dict:
	"""Re-run the pricing rules for one item or every item of a category."""
	_check_edit(PRICE_KEYS)
	if not (reason or "").strip():
		frappe.throw(_("Give a reason, for example the supplier's new price list."))
	if item_code:
		items = [item_code]
	elif category:
		items = frappe.get_all(
			"Item", filters={"sp_price_age_category": category, "disabled": 0}, pluck="name"
		)
	else:
		frappe.throw(_("Choose an item or a category."))
	changed = {code: prices.apply_category_rules(code, reason=reason) for code in items}
	return {"items": len(items), "changed": sum(bool(v) for v in changed.values())}


@frappe.whitelist()
def price_history(item_code: str) -> list[dict]:
	"""Every price change of the item: when, who, which list, old → new, and the reason.

	Buying lists are left out for users without cost access.
	"""
	frappe.get_doc("Item", item_code).check_permission("read")
	lists = {name: key for key, name in prices.price_lists().items() if name}
	sees_cost = can_see_cost()
	item_prices = frappe.get_all(
		"Item Price",
		filters={"item_code": item_code, "price_list": ("in", list(lists))},
		fields=["name", "price_list", "supplier", "price_list_rate", "creation", "owner"],
	)
	item_prices = [p for p in item_prices if sees_cost or lists[p.price_list] not in COST_SIDE]
	by_name = {p.name: p for p in item_prices}
	if not by_name:
		return []
	entries = []
	reasons = frappe.get_all(
		"SP Edit Reason Log",
		filters={
			"reference_doctype": "Item Price",
			"reference_name": ("in", list(by_name)),
			"fieldname": "price_list_rate",
		},
		fields=["reference_name", "old_value", "new_value", "reason", "user", "creation"],
	)
	logged = set()
	for r in reasons:
		entries.append(
			_entry(by_name[r.reference_name], lists, r.creation, r.user, r.old_value, r.new_value, r.reason)
		)
		logged.add((r.reference_name, flt(r.new_value)))
	for version in frappe.get_all(
		"Version",
		filters={"ref_doctype": "Item Price", "docname": ("in", list(by_name))},
		fields=["docname", "data", "owner", "creation"],
	):
		for field, old, new in _parse(version.data).get("changed", []):
			old, new = _number(old), _number(new)
			if field == "price_list_rate" and (version.docname, new) not in logged:
				entries.append(
					_entry(by_name[version.docname], lists, version.creation, version.owner, old, new, None)
				)
	first = {}
	for p in item_prices:
		first_rate = p.price_list_rate
		changes = sorted((e for e in entries if e["item_price"] == p.name), key=lambda e: e["at"])
		if changes:
			first_rate = changes[0]["old"]
		first[p.name] = _entry(p, lists, p.creation, p.owner, None, first_rate, None)
	entries.extend(first.values())
	entries.sort(key=lambda e: e["at"], reverse=True)
	return entries


def _number(value) -> float | None:
	"""A number from a Version entry, which stores money formatted ("5,500.00 EGP")."""
	if value in (None, ""):
		return None
	if isinstance(value, int | float):
		return flt(value)
	fmt = NumberFormat.from_string(
		frappe.db.get_single_value("System Settings", "number_format") or "#,###.##"
	)
	text = str(value)
	if fmt.thousands_separator:
		text = text.replace(fmt.thousands_separator, "")
	text = re.sub(rf"[^\d{re.escape(fmt.decimal_separator)}-]", "", text).replace(fmt.decimal_separator, ".")
	return flt(text)


def _entry(item_price, lists, at, user, old, new, reason) -> dict:
	key = lists[item_price.price_list]
	return {
		"item_price": item_price.name,
		"at": at,
		"user": user,
		"user_name": frappe.utils.get_fullname(user),
		"price_list": key,
		"price_list_label": _(prices.price_list_label(key)),
		"supplier": item_price.supplier,
		"old": flt(old) if old not in (None, "") else None,
		"new": flt(new) if new not in (None, "") else None,
		"reason": reason,
	}
