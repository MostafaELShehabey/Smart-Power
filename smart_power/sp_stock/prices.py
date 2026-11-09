"""The price list model (SP-30, I2).

Four ERPNext price lists, named in Smart Power Settings:

- List Price: the supplier's catalogue price (buying, one row per supplier)
- P1 Cost: Smart Power's cost (buying, one row per supplier)
- BTB: the sale price for companies (selling)
- BTC: the sale price for individuals (selling)

Every Item Price row carries its price date in `valid_from`, and buying rows carry their
supplier, so one item can hold prices from several suppliers, each with its own date. When a
price changes its date moves to the day of the change, the old and new values are kept in
the Item Price version history, and a change made through this module needs a reason, which
goes to SP Edit Reason Log.

An SP Price Category gives the age limit (green, amber, red) and the pricing rules, the way
the Excel sheet's section headers work today: for example P1 Cost = List Price less 13%, and
BTC = List Price less 3% plus a fixed amount. The numbers in the rules are the admin's data.
"""

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.utils import date_diff, flt, getdate, today

from smart_power.sp_core.services.settings import get_settings

PCT = 100

LIST, COST, BTB, BTC = "list", "cost", "btb", "btc"
PRICE_KEYS = (LIST, COST, BTB, BTC)
SETTINGS_FIELD = {
	LIST: "list_price_list",
	COST: "cost_price_list",
	BTB: "btb_price_list",
	BTC: "btc_price_list",
}
# Buying-side lists: each row names its supplier, and only cost roles see them (SP-35).
COST_SIDE = (LIST, COST)
# Customer tier → the sale price list (SP-30: individual = BTC, company = BTB).
TIER_LIST = {"Individual": BTC, "Company": BTB}
# SP Price Rule options → price keys.
RULE_TARGET = {"P1 Cost": COST, "BTB": BTB, "BTC": BTC}
RULE_BASE = {"List Price": LIST, "P1 Cost": COST, "BTC": BTC}

FRESH, AGING, STALE, NO_LIMIT, NO_PRICE = "fresh", "aging", "stale", "no_limit", "no_price"


# --- the four lists ---------------------------------------------------------------------------


def price_lists() -> dict[str, str | None]:
	"""{key: Price List name} from Smart Power Settings."""
	settings = get_settings()
	return {key: settings.get(field) for key, field in SETTINGS_FIELD.items()}


def price_list(key: str) -> str:
	name = price_lists().get(key)
	if not name:
		frappe.throw(
			_("Set the {0} price list in Smart Power Settings.").format(_(price_list_label(key))),
			title=_("Price lists are not set"),
		)
	return name


def price_list_label(key: str) -> str:
	return {LIST: "Supplier List Price", COST: "P1 Cost", BTB: "BTB (Companies)", BTC: "BTC (Individuals)"}[
		key
	]


def key_of(price_list_name: str | None) -> str | None:
	"""The key (list, cost, btb, btc) of a price list, or None for any other list."""
	if not price_list_name:
		return None
	for key, name in price_lists().items():
		if name == price_list_name:
			return key
	return None


def seed_price_lists() -> None:
	"""Create the four price lists from defaults.json and link them in Smart Power Settings.

	Existing lists and links are kept, so the admin can rename a list or point a key elsewhere.
	"""
	from smart_power.sp_core.setup.seed import defaults

	spec = {k: v for k, v in defaults()["price_lists"].items() if not k.startswith("_")}
	currency = frappe.db.get_default("currency") or defaults()["system_settings"]["currency"]
	settings = frappe.get_single("Smart Power Settings")
	changed = False
	for key, row in spec.items():
		if not frappe.db.exists("Price List", row["name"]):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": row["name"],
					"currency": currency,
					"buying": row.get("buying", 0),
					"selling": row.get("selling", 0),
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		field = SETTINGS_FIELD[key]
		if not settings.get(field):
			settings.set(field, row["name"])
			changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.save()


# --- categories -------------------------------------------------------------------------------


def category_of(item_code: str) -> str | None:
	"""The item's price category, or its item group's."""
	category, group = frappe.get_cached_value("Item", item_code, ["sp_price_age_category", "item_group"])
	return category or (group and frappe.get_cached_value("Item Group", group, "sp_price_age_category"))


def seed_price_categories() -> None:
	"""One price category per catalogue item group (no age limit until the admin sets one)."""
	from smart_power.sp_core.setup.seed import defaults

	for name in defaults()["item_groups"]["names"]:
		if not frappe.db.exists("SP Price Category", name):
			frappe.get_doc({"doctype": "SP Price Category", "category_name": name}).insert(
				ignore_permissions=True
			)
		if frappe.db.exists("Item Group", name) and not frappe.db.get_value(
			"Item Group", name, "sp_price_age_category"
		):
			frappe.db.set_value("Item Group", name, "sp_price_age_category", name)


def age_status(age_days: int | None, category: str | None) -> str:
	"""fresh (green), aging (amber), stale (red), no_limit (grey) or no_price."""
	if age_days is None:
		return NO_PRICE
	if not category:
		return NO_LIMIT
	max_days, amber_days = frappe.get_cached_value(
		"SP Price Category", category, ["max_age_days", "amber_after_days"]
	)
	if not max_days and not amber_days:
		return NO_LIMIT
	if max_days and age_days > max_days:
		return STALE
	if amber_days and age_days > amber_days:
		return AGING
	return FRESH


# --- reading prices ---------------------------------------------------------------------------


def latest_price(item_code: str, key: str, supplier: str | None = None, on_date=None) -> frappe._dict | None:
	"""The newest price of one list valid on a date: {name, rate, date, supplier}.

	For a buying list without a supplier, the item's main supplier wins, then the newest row.
	"""
	name = price_lists().get(key)
	if not name:
		return None
	on_date = getdate(on_date or today())
	ip = frappe.qb.DocType("Item Price")

	def query(only_supplier=None):
		q = (
			frappe.qb.from_(ip)
			.select(
				ip.name, ip.price_list_rate.as_("rate"), ip.valid_from.as_("date"), ip.supplier, ip.creation
			)
			.where((ip.item_code == item_code) & (ip.price_list == name))
			.where(ip.valid_from.isnull() | (ip.valid_from <= on_date))
			.where(ip.valid_upto.isnull() | (ip.valid_upto >= on_date))
			.orderby(ip.valid_from, order=Order.desc)
			.orderby(ip.modified, order=Order.desc)
			.limit(1)
		)
		if only_supplier:
			q = q.where(ip.supplier == only_supplier)
		rows = q.run(as_dict=True)
		if not rows:
			return None
		row = rows[0]
		row.date = getdate(row.date or row.creation)
		return row

	if key in COST_SIDE:
		preferred = supplier or frappe.get_cached_value("Item", item_code, "sp_main_supplier")
		if preferred:
			row = query(preferred)
			if row or supplier:
				return row
	return query()


def item_prices(item_code: str, on_date=None) -> dict[str, frappe._dict | None]:
	return {key: latest_price(item_code, key, on_date=on_date) for key in PRICE_KEYS}


def get_price(
	item_code: str, tier: str = "Individual", on_date=None, supplier: str | None = None
) -> frappe._dict:
	"""The sale price for a customer tier, with the cost and the price age.

	Returns {price, price_date, price_list, cost, cost_date, cost_supplier, age_days, is_stale,
	age_status, category}. The age is that of the older of the sale price and the cost: a stale
	cost makes the margin wrong even when the sale price is fresh. The cost is returned to
	server code only; the APIs strip it for users who may not see it (SP-35).
	"""
	on_date = getdate(on_date or today())
	key = TIER_LIST.get(tier, BTC)
	sale = latest_price(item_code, key, on_date=on_date)
	cost = latest_price(item_code, COST, supplier=supplier, on_date=on_date)
	dates = [row.date for row in (sale, cost) if row]
	age = date_diff(on_date, min(dates)) if dates else None
	category = category_of(item_code)
	status = age_status(age, category)
	return frappe._dict(
		price=sale.rate if sale else None,
		price_date=sale.date if sale else None,
		price_list=price_lists().get(key),
		cost=cost.rate if cost else None,
		cost_date=cost.date if cost else None,
		cost_supplier=cost.supplier if cost else None,
		age_days=age,
		is_stale=status == STALE,
		age_status=status,
		category=category,
	)


# --- writing prices ---------------------------------------------------------------------------


def _same(a, b) -> bool:
	precision = frappe.get_precision("Item Price", "price_list_rate")
	return flt(a, precision) == flt(b, precision)


def set_price(
	item_code: str,
	key: str,
	rate: float,
	*,
	supplier: str | None = None,
	price_date=None,
	reason: str | None = None,
) -> tuple[str, bool]:
	"""Create or change one price. Returns (Item Price name, changed).

	Changing an existing price needs a reason; its date becomes price_date (default today).
	Permissions are those of the current user.
	"""
	from smart_power.sp_core.services.audit import log_edit

	name = price_list(key)
	if key in COST_SIDE:
		supplier = supplier or frappe.get_cached_value("Item", item_code, "sp_main_supplier")
		if not supplier:
			frappe.throw(
				_("{0}: a {1} price needs a supplier.").format(item_code, _(price_list_label(key))),
				title=_("Supplier missing"),
			)
	else:
		supplier = None
	price_date = getdate(price_date or today())
	rate = flt(rate)

	existing = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": name, "supplier": supplier or ("is", "not set")},
		["name", "price_list_rate", "valid_from"],
		as_dict=True,
		order_by="valid_from desc, modified desc",
	)
	if existing:
		if _same(existing.price_list_rate, rate) and getdate(existing.valid_from or price_date) >= price_date:
			return existing.name, False
		doc = frappe.get_doc("Item Price", existing.name)
		old = doc.price_list_rate
		if not _same(old, rate) and not (reason or "").strip():
			frappe.throw(
				_("{0}: give a reason for changing the {1} price.").format(
					item_code, _(price_list_label(key))
				),
				title=_("A reason is needed"),
			)
		doc.price_list_rate = rate
		doc.valid_from = price_date
		doc.save()
		if not _same(old, rate):
			log_edit(doc, "price_list_rate", old, rate, reason)
		return doc.name, True

	doc = frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": item_code,
			"price_list": name,
			"price_list_rate": rate,
			"supplier": supplier,
			"valid_from": price_date,
			"uom": frappe.get_cached_value("Item", item_code, "stock_uom"),
		}
	).insert()
	return doc.name, True


# --- pricing rules ----------------------------------------------------------------------------


def round_price(value: float, step: float | None) -> float:
	step = flt(step)
	if step:
		return round(flt(value) / step) * step
	return flt(value, frappe.get_precision("Item Price", "price_list_rate"))


def rounding_step(category: str | None) -> float:
	step = category and frappe.get_cached_value("SP Price Category", category, "rounding_step")
	return flt(step) or flt(get_settings().default_rounding_step)


def derive_prices(rules, known: dict[str, float], step: float = 0) -> dict[str, float]:
	"""Work out the rule targets from the known prices. Pure: nothing is read or written.

	A rule computes base * (1 + change % / 100) + add amount. Rules whose base is itself
	derived run after it. A target that is already known is left alone.
	"""
	values = {k: flt(v) for k, v in known.items() if v is not None}
	pending = [r for r in rules if RULE_TARGET[r.target] not in values]
	derived: dict[str, float] = {}
	while pending:
		ready = [r for r in pending if RULE_BASE[r.base] in values]
		if not ready:
			break
		for r in ready:
			base = values[RULE_BASE[r.base]]
			value = round_price(base * (1 + flt(r.adjust_pct) / PCT) + flt(r.add_amount), step)
			values[RULE_TARGET[r.target]] = derived[RULE_TARGET[r.target]] = value
			pending.remove(r)
	return derived


def apply_category_rules(
	item_code: str, reason: str, price_date=None, given: dict[str, float] | None = None
) -> dict[str, float]:
	"""Recompute the item's rule-driven prices from its current prices and save them.

	`given` holds prices the user just set by hand: they are kept and feed the rules that
	depend on them (BTC typed in, so BTB = BTC less 5% follows). Items marked Manual Prices,
	and items whose category has no rules, are left alone. Returns {key: new price} for the
	prices that changed.
	"""
	if frappe.get_cached_value("Item", item_code, "sp_manual_prices"):
		return {}
	category = category_of(item_code)
	if not category:
		return {}
	rules = frappe.get_cached_doc("SP Price Category", category).rules
	if not rules:
		return {}
	given = given or {}
	targets = {RULE_TARGET[r.target] for r in rules}
	current = item_prices(item_code)
	known = {k: row.rate for k, row in current.items() if row and k not in targets}
	known.update(given)
	derived = derive_prices(rules, known, rounding_step(category))
	supplier = (current.get(LIST) or current.get(COST) or frappe._dict()).get("supplier")
	changed = {}
	for key, value in derived.items():
		_name, did_change = set_price(
			item_code,
			key,
			value,
			supplier=supplier if key in COST_SIDE else None,
			price_date=price_date,
			reason=reason,
		)
		if did_change:
			changed[key] = value
	return changed


# --- hooks ------------------------------------------------------------------------------------


def validate_item_price(doc, method=None) -> None:
	"""Item Price validate hook, for Smart Power's four lists only.

	- every price has a date; a changed price gets today's date unless the date was changed too
	- a buying price without a supplier takes the item's main supplier
	"""
	key = key_of(doc.price_list)
	if not key:
		return
	if not doc.valid_from:
		doc.valid_from = today()
	before = doc.get_doc_before_save() if not doc.is_new() else None
	if (
		before
		and not _same(before.price_list_rate, doc.price_list_rate)
		and getdate(before.valid_from) == getdate(doc.valid_from)
	):
		doc.valid_from = today()
	if key in COST_SIDE and not doc.supplier:
		doc.supplier = frappe.get_cached_value("Item", doc.item_code, "sp_main_supplier")
