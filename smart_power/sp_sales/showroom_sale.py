"""SH1 Showroom sale (SP-102): the cashier sells from the showroom store and prints a receipt.

A sale is an ERPNext POS Sales Invoice numbered SHR-.YYYY.-.##### that updates the stock of the
showroom store, posts its income to «مبيعات المعرض» (Showroom Sales) on the Showroom center, and
is paid at once: cash goes into the showroom box (خزنة المعرض, Showroom Safe), so the box's day
(SP-104) counts it in "Sales in"; another method goes to its official account.

    options()                   the store, the box, the walk-in customer and the payment methods
    find_customer(mobile)       a customer by mobile, with the price list of their tier
    find_items(q, customer)     the items, with the showroom store's stock and the sale price
    sell(values)                record, post and number the sale
    return_sale(invoice, items) items back into the store, the money back out of the box
    receipt(name)               the printed receipt (SP Showroom Receipt)
    today_sales()               the receipts of the day

The owner's decisions (2026-11-21): one walk-in customer «عميل نقدي» at BTC prices for every
walk-in sale; a sale by mobile links the real customer (a company gets BTB). There is no
discount limit until the admin sets Showroom Discount Limit; every discount is listed in the
Review centre meanwhile.

Serials (SP-179): a motor or pump is sold one unit at a time, each with a serial in the showroom
store and a new nameplate photo (owner, 2026-11-22); without them the sale is refused. Each sold
serial joins the warranty register from the sale date, for the item's warranty years, else its
brand's. A return names the serials that come back, and their warranty is void.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt, nowdate

from smart_power.sp_finance.centers import SHOWROOM as SHOWROOM_CENTER
from smart_power.sp_finance.centers import center
from smart_power.sp_finance.customer_payment import can_use_showroom_box, showroom_box_account
from smart_power.sp_sales.customer import WALK_IN
from smart_power.sp_stock.prices import BTB, BTC, TIER_LIST, key_of, latest_price, price_list
from smart_power.sp_stock.warehouses import SHOWROOM as SHOWROOM_STORE
from smart_power.sp_stock.warehouses import warehouse_of

SI = "Sales Invoice"
PROFILE = "POS Profile"
SERIES = "SHR-.YYYY.-.#####"
PROFILE_NAME = "Showroom"  # one per company: "Showroom - <abbr>"
REVENUE_ACCOUNT = "Showroom Sales"
RECEIPT_FORMAT = "SP Showroom Receipt"
CASH_TYPE = "Cash"
SALE_LISTS = (BTC, BTB)
NO_SALE_MODES = ("Postal Cheque",)  # a cheque is not paid at the counter
RESULTS = 20  # sp-allow-number: items listed for one search, a screen size
TODAY_SHOWN = 50  # sp-allow-number: today's receipts listed, a screen size
MIN_SEARCH = 2  # sp-allow-number: letters before an item search runs
QTY_DIGITS = 3  # sp-allow-number: quantity precision of a sale line
MONEY_DIGITS = 2  # sp-allow-number: piastres
SERIALS_SHOWN = 100  # sp-allow-number: serials of one item offered at the counter
MONTHS_PER_YEAR = 12  # sp-allow-number: a calendar fact
PCT = 100


def _check() -> None:
	if not can_use_showroom_box():
		frappe.throw(_("Only the showroom cashier sells at the showroom."), frappe.PermissionError)


def _company() -> str | None:
	"""The cashier's company, else Smart Power's (as the cash box, SP-104)."""
	return (
		frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("SP Company Settings", "company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)


def _as_system(action):
	from smart_power.sp_stock.transfers import _as_system

	return _as_system(action)


# --- setup ------------------------------------------------------------------------------------


def ensure_series() -> None:
	from smart_power.sp_stations.close import ensure_invoice_series

	ensure_invoice_series(SERIES)


def seed_walk_in() -> str:
	"""«عميل نقدي»: the one customer of every walk-in sale, an individual at BTC prices."""
	name = frappe.db.get_value("Customer", {"customer_name": WALK_IN})
	if name:
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": WALK_IN,
			"sp_tier": "Individual",
			"customer_type": "Individual",
		}
	)
	doc.flags.sp_walk_in = True  # it has no mobile
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def is_walk_in(customer: str | None) -> bool:
	return bool(customer) and frappe.db.get_value("Customer", customer, "customer_name") == WALK_IN


def profile_name(company: str) -> str:
	return f"{PROFILE_NAME} - {frappe.get_cached_value('Company', company, 'abbr')}"


def sale_modes(company: str) -> list[dict]:
	"""The Smart Power modes of payment that have an account in the company, cash first."""
	from smart_power.sp_finance.accounts import _spec

	modes = []
	for row in _spec()["modes_of_payment"]:
		if row["mode"] in NO_SALE_MODES or not frappe.db.exists("Mode of Payment", row["mode"]):
			continue
		account = mode_account(row["mode"], company)
		if account:
			modes.append({"mode": row["mode"], "account": account, "is_cash": row["type"] == CASH_TYPE})
	return sorted(modes, key=lambda m: not m["is_cash"])


def mode_account(mode: str, company: str) -> str | None:
	if frappe.get_cached_value("Mode of Payment", mode, "type") == CASH_TYPE:
		return showroom_box_account(company)
	return frappe.db.get_value(
		"Mode of Payment Account", {"parent": mode, "company": company}, "default_account"
	)


def seed_pos_profile(company: str) -> str | None:
	"""The company's showroom POS profile: the showroom store, the Showroom center, Showroom Sales,
	the walk-in customer and the payment methods. Skipped while a piece is missing."""
	ensure_series()
	name = profile_name(company)
	if frappe.db.exists(PROFILE, name):
		return name
	store = warehouse_of(company, SHOWROOM_STORE)
	box = showroom_box_account(company)
	revenue = _revenue_account(company)
	cost_center = center(SHOWROOM_CENTER, company)
	modes = sale_modes(company)
	if not (store and box and revenue and cost_center and modes):
		return None
	company_doc = frappe.get_cached_doc("Company", company)
	doc = frappe.get_doc(
		{
			"doctype": PROFILE,
			"name": name,
			"company": company,
			"customer": seed_walk_in(),
			"warehouse": store,
			"update_stock": 1,
			"cost_center": cost_center,
			"income_account": revenue,
			"write_off_account": company_doc.write_off_account,
			"write_off_cost_center": cost_center,
			"account_for_change_amount": box,
			"currency": company_doc.default_currency,
			"selling_price_list": price_list(BTC),
			"ignore_pricing_rule": 1,
			"disable_rounded_total": 1,
			"payments": [{"mode_of_payment": m["mode"], "default": int(m["is_cash"])} for m in modes],
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _revenue_account(company: str) -> str | None:
	return frappe.db.get_value(
		"Account", {"company": company, "account_name": REVENUE_ACCOUNT, "is_group": 0, "disabled": 0}
	)


def _profile(company: str):
	name = profile_name(company)
	if not frappe.db.exists(PROFILE, name):
		name = _as_system(lambda: seed_pos_profile(company))
	if not name:
		frappe.throw(
			_(
				"The showroom is not set up for {0}: it needs the showroom store, the box and Showroom Sales."
			).format(company)
		)
	return frappe.get_cached_doc(PROFILE, name)


def is_showroom(doc) -> bool:
	return doc.get("doctype") == SI and doc.get("naming_series") == SERIES


def pin_box(doc, method=None) -> None:
	"""Sales Invoice before_save: ERPNext takes each payment's account from its Mode of Payment;
	a showroom sale's cash always goes into the showroom box."""
	if not is_showroom(doc):
		return
	box = showroom_box_account(doc.company)
	for row in doc.get("payments") or []:
		if box and frappe.get_cached_value("Mode of Payment", row.mode_of_payment, "type") == CASH_TYPE:
			row.account = box


# --- pricing ----------------------------------------------------------------------------------


def price_key(customer: str | None) -> str:
	"""BTC, or BTB for a company: the customer's own sale price list, else their tier's."""
	if not customer:
		return BTC
	tier, default_list = frappe.db.get_value("Customer", customer, ["sp_tier", "default_price_list"]) or (
		None,
		None,
	)
	key = key_of(default_list)
	return key if key in SALE_LISTS else TIER_LIST.get(tier, BTC)


def sale_price(item_code: str, key: str) -> float | None:
	row = latest_price(item_code, key)
	return flt(row.rate) if row else None


def sale_discount(doc) -> float:
	"""What the customer was given off the price list: line discounts and the total discount."""
	listed = sum(flt(r.price_list_rate) * flt(r.qty) for r in doc.items)
	return max(flt(listed - flt(doc.grand_total), MONEY_DIGITS), 0.0)


def discount_pct(doc) -> float:
	listed = sum(flt(r.price_list_rate) * flt(r.qty) for r in doc.items)
	return sale_discount(doc) / listed * PCT if listed else 0.0


# --- the page's calls -------------------------------------------------------------------------


@frappe.whitelist()
def options() -> dict:
	_check()
	company = _company()
	profile = _profile(company)
	arabic = frappe.local.lang == "ar"
	return {
		"company": company,
		"store": profile.warehouse,
		"box": showroom_box_account(company),
		"walk_in": {"name": profile.customer, "customer_name": WALK_IN, "price_list": _list_label(BTC)},
		"modes": [
			{**m, "label": _(m["mode"]) if arabic else m["mode"]}
			for m in sale_modes(company)
			if any(p.mode_of_payment == m["mode"] for p in profile.payments)
		],
		"today": nowdate(),
	}


def _list_label(key: str) -> str:
	from smart_power.sp_stock.prices import price_list_label

	return price_list_label(key)


@frappe.whitelist()
def find_customer(mobile: str) -> dict | None:
	"""The customer of this mobile: the sale is theirs, at their tier's prices."""
	_check()
	from smart_power.sp_sales.customer import find_by_mobile, normalize_mobile

	name = find_by_mobile(normalize_mobile(mobile)) if mobile else None
	if not name:
		return None
	key = price_key(name)
	return {
		"name": name,
		"customer_name": frappe.db.get_value("Customer", name, "customer_name"),
		"price_key": key,
		"price_list": _list_label(key),
	}


@frappe.whitelist()
def find_items(q: str, customer: str | None = None) -> list[dict]:
	"""Items matching every word, with the showroom store's stock and the customer's price."""
	_check()
	from smart_power.sp_stock.item_search import items_matching_all, split_words

	words = split_words(q)
	if len("".join(words)) < MIN_SEARCH:
		return []
	names = items_matching_all(words)
	if not names:
		return []
	store = _profile(_company()).warehouse
	items = frappe.get_all(
		"Item",
		{"name": ("in", names), "disabled": 0, "is_sales_item": 1, "has_variants": 0},
		["name", "item_name", "sp_name_ar", "stock_uom", "has_serial_no"],
		limit=len(names),
	)
	stock = dict(
		frappe.get_all(
			"Bin",
			{"warehouse": store, "item_code": ("in", [i.name for i in items] or [""])},
			["item_code", "actual_qty"],
			as_list=True,
		)
	)
	key = price_key(customer)
	rows = [
		{
			"item_code": i.name,
			"item_name": i.sp_name_ar or i.item_name,
			"uom": i.stock_uom,
			"in_stock": flt(stock.get(i.name)),
			"price": sale_price(i.name, key),
			"serial": bool(i.has_serial_no),
		}
		for i in items
	]
	rows.sort(key=lambda r: (r["in_stock"] <= 0, r["item_name"] or ""))
	return rows[:RESULTS]


@frappe.whitelist()
def store_serials(item_code: str) -> list[str]:
	"""The serials of an item in the showroom store, for the cashier to pick (SP-179)."""
	_check()
	store = _profile(_company()).warehouse
	return frappe.get_all(
		"Serial No",
		{"item_code": item_code, "warehouse": store, "status": "Active"},
		pluck="name",
		order_by="name asc",
		limit=SERIALS_SHOWN,
	)


def _line_serials(row: dict, qty: float, store: str, taken: set) -> tuple[list[str], dict]:
	"""A serial-tracked line: one serial in the store and a nameplate photo for each unit."""
	from smart_power.sp_stock.serials import check_photos, unit_serials

	units = row.get("serials") or []
	serials = unit_serials(row["item_code"], qty, [u.get("serial_no") for u in units])
	photos = {cstr(u.get("serial_no")).strip(): u.get("photo") for u in units}
	check_photos(row["item_code"], serials, photos)
	for serial in serials:
		place = frappe.db.get_value("Serial No", serial, ["item_code", "warehouse", "status"], as_dict=True)
		if not place or place.item_code != row["item_code"] or place.warehouse != store:
			frappe.throw(
				_("Serial number {0} of {1} is not in the showroom store.").format(
					frappe.bold(serial), row["item_code"]
				)
			)
		if serial in taken:
			frappe.throw(_("Serial number {0} is entered twice.").format(frappe.bold(serial)))
		taken.add(serial)
	return serials, photos


def _clean_lines(lines: list[dict], key: str, store: str) -> list[dict]:
	from smart_power.sp_stock.serials import is_serial

	clean, wanted, taken = [], {}, set()
	for row in lines or []:
		qty = flt(row.get("qty"), QTY_DIGITS)
		if not row.get("item_code") or qty <= 0:
			frappe.throw(_("Enter each item with a quantity above zero."))
		wanted[row["item_code"]] = wanted.get(row["item_code"], 0) + qty
		price = sale_price(row["item_code"], key)
		if not price:
			frappe.throw(
				_("{0} has no price on {1}.").format(frappe.bold(row["item_code"]), _list_label(key))
			)
		line_pct = flt(row.get("discount_pct"))
		if not 0 <= line_pct < PCT:
			frappe.throw(_("A line discount is a percent between 0 and 100."))
		line = {
			"item_code": row["item_code"],
			"qty": qty,
			"price_list_rate": price,
			"discount_percentage": line_pct,
			"rate": flt(price * (1 - line_pct / PCT), MONEY_DIGITS),
			"warehouse": store,
		}
		if is_serial(row["item_code"]):
			serials, photos = _line_serials(row, qty, store, taken)
			line.update(use_serial_batch_fields=1, serial_no="\n".join(serials), photos=photos)
		clean.append(line)
	if not clean:
		frappe.throw(_("Add at least one item."))
	for item_code, qty in wanted.items():
		have = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": store}, "actual_qty"))
		if qty > have:
			frappe.throw(
				_("The showroom store has {0} of {1}; the sale needs {2}.").format(
					frappe.format(have, "Float"), frappe.bold(item_code), frappe.format(qty, "Float")
				)
			)
	return clean


def _mode(mode: str | None, profile) -> str:
	allowed = [p.mode_of_payment for p in profile.payments]
	mode = mode or next((p.mode_of_payment for p in profile.payments if p.default), None)
	if mode not in allowed:
		frappe.throw(_("{0} is not a payment method of the showroom.").format(frappe.bold(mode)))
	return mode


@frappe.whitelist(methods=["POST"])
def sell(values: str | dict) -> dict:
	"""Post the sale: a POS Sales Invoice paid in full, cash into the box."""
	_check()
	values = frappe.parse_json(values) or {}
	company = _company()
	profile = _profile(company)
	customer = values.get("customer") or profile.customer
	key = price_key(None if is_walk_in(customer) else customer)
	lines = _clean_lines(values.get("items"), key, profile.warehouse)
	mode = _mode(values.get("mode_of_payment"), profile)
	total_discount = flt(values.get("discount_amount"), MONEY_DIGITS)
	if total_discount < 0:
		frappe.throw(_("The discount cannot be negative."))
	user = frappe.session.user

	def build():
		si = frappe.get_doc(
			{
				"doctype": SI,
				"naming_series": SERIES,
				"company": company,
				"customer": customer,
				"is_pos": 1,
				"pos_profile": profile.name,
				"update_stock": 1,
				"set_warehouse": profile.warehouse,
				"posting_date": nowdate(),
				"selling_price_list": price_list(key),
				"ignore_pricing_rule": 1,
				"disable_rounded_total": 1,
				"cost_center": profile.cost_center,
				"apply_discount_on": "Grand Total",
				"discount_amount": total_discount,
				"remarks": values.get("reference_no") or None,
				"items": [
					{
						**{k: v for k, v in line.items() if k != "photos"},
						"income_account": profile.income_account,
						"cost_center": profile.cost_center,
					}
					for line in lines
				],
			}
		)
		si.set_missing_values()
		_pin_lines(si, lines, profile)
		si.calculate_taxes_and_totals()
		if flt(si.grand_total) <= 0:
			frappe.throw(_("The discount is more than the sale."))
		si.set("payments", [{"mode_of_payment": mode, "amount": si.grand_total, "default": 1}])
		si.insert()
		si.submit()
		return si

	si = _as_system(build)
	_signed_by(si.name, user)
	_review_discount(si)
	_register_serials(si, lines)
	return {"name": si.name, "grand_total": flt(si.grand_total), "discount": sale_discount(si)}


def warranty_months(item_code: str) -> int:
	"""The item's warranty years, else its brand's (SP-179), in months; 0 when neither is set."""
	years, brand = frappe.db.get_value("Item", item_code, ["sp_warranty_years", "brand"])
	if not flt(years) and brand:
		years = frappe.db.get_value("Brand", brand, "sp_warranty_years")
	return round(flt(years) * MONTHS_PER_YEAR)


def _register_serials(si, lines: list[dict]) -> None:
	"""The nameplate photos and a warranty row for each sold serial, from the sale date."""
	from smart_power.sp_stock.serials import SHOWROOM_SALE, record_photos
	from smart_power.sp_stock.warranty import SALE_DATE, SHOWROOM, upsert

	for line in lines:
		if not line.get("serial_no"):
			continue
		serials = line["serial_no"].split("\n")
		record_photos(SHOWROOM_SALE, line["item_code"], serials, line["photos"], SI, si.name, si.posting_date)
		months = warranty_months(line["item_code"])
		for serial in serials:
			upsert(
				serial,
				line["item_code"],
				{
					"source": SHOWROOM,
					"sales_invoice": si.name,
					"customer": si.customer,
					"start_basis": SALE_DATE,
					"start_date": si.posting_date,
					"months": months,
					"nameplate_photo": line["photos"][serial],
				},
			)


def _pin_lines(si, lines: list[dict], profile) -> None:
	"""ERPNext fills a line from the price list again; keep the price and discount the cashier saw."""
	for row, line in zip(si.items, lines, strict=True):
		row.update(
			{
				"price_list_rate": line["price_list_rate"],
				"discount_percentage": line["discount_percentage"],
				"rate": line["rate"],
				"warehouse": profile.warehouse,
				"income_account": profile.income_account,
				"cost_center": profile.cost_center,
			}
		)
		if line.get("serial_no"):
			row.update({"use_serial_batch_fields": 1, "serial_no": line["serial_no"]})


def _signed_by(name: str, user: str) -> None:
	"""The receipt shows the cashier who sold, not the system that posted it."""
	frappe.db.set_value(SI, name, {"owner": user, "modified_by": user}, update_modified=False)


def _review_discount(si) -> None:
	"""Every showroom discount is listed for the admin; the limit rule highlights one above it."""
	from smart_power.sp_core.review_centre import raise_item

	discount = sale_discount(si)
	if not discount:
		return
	filters = {"category": "Discount", "reference_doctype": SI, "reference_name": si.name, "status": "Open"}
	if frappe.db.exists("SP Review Item", filters):  # the limit rule already listed it
		return
	raise_item(
		"Discount",
		si,
		_("Showroom discount {0} ({1}%) on {2}").format(
			frappe.format(discount, "Currency"),
			frappe.format(flt(discount_pct(si), 1), "Float"),
			si.customer_name,
		),
		amount=discount,
	)


@frappe.whitelist(methods=["POST"])
def return_sale(invoice: str, items: str | list) -> dict:
	"""Return items of an earlier receipt: they go back into the showroom store and the money
	goes back out of the showroom box in cash."""
	_check()
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	original = frappe.get_doc(SI, invoice)
	if not is_showroom(original) or original.docstatus != 1 or original.is_return:
		frappe.throw(_("{0} is not a showroom receipt.").format(frappe.bold(invoice)))
	from smart_power.sp_stock.serials import is_serial, unit_serials

	wanted, back = {}, {}
	for row in frappe.parse_json(items) or []:
		qty = flt(row.get("qty"), QTY_DIGITS)
		if row.get("item_code") and qty > 0:
			wanted[row["item_code"]] = wanted.get(row["item_code"], 0) + qty
			if is_serial(row["item_code"]):
				back.setdefault(row["item_code"], []).extend(
					unit_serials(row["item_code"], qty, row.get("serials") or [])
				)
	if not wanted:
		frappe.throw(_("Choose the items to return and their quantity."))
	sold = returnable_serials(original)
	for item_code, serials in back.items():
		strange = [s for s in serials if s not in sold.get(item_code, [])]
		if strange:
			frappe.throw(
				_("{0} was not sold on {1}, or is already returned.").format(", ".join(strange), invoice)
			)
	left = returnable(original)
	for item_code, qty in wanted.items():
		if item_code not in left:
			frappe.throw(_("{0} is not on the receipt.").format(frappe.bold(item_code)))
		if qty > left[item_code]:
			frappe.throw(
				_("Only {0} of {1} is left to return on {2}.").format(
					frappe.format(left[item_code], "Float"), frappe.bold(item_code), invoice
				)
			)
	cash = next(p.mode_of_payment for p in _profile(original.company).payments if p.default)
	user = frappe.session.user

	def build():
		ret = make_return_doc(SI, invoice)
		ret.naming_series = SERIES
		ret.posting_date = nowdate()
		kept = []
		for row in ret.items:
			left = wanted.get(row.item_code, 0)
			if not left:
				continue
			qty = min(left, abs(flt(row.qty)))
			wanted[row.item_code] = left - qty
			row.qty = -qty
			row.stock_qty = -qty * flt(row.conversion_factor or 1)
			if row.item_code in back:  # the serials that come back (SP-179)
				units = back[row.item_code][: int(qty)]
				back[row.item_code] = back[row.item_code][int(qty) :]
				row.serial_and_batch_bundle = None
				row.use_serial_batch_fields = 1
				row.serial_no = "\n".join(units)
			kept.append(row)
		ret.set("items", kept)
		ret.calculate_taxes_and_totals()
		ret.set("payments", [{"mode_of_payment": cash, "amount": ret.grand_total, "default": 1}])
		ret.insert()
		ret.submit()
		return ret

	returned = {s for row in frappe.parse_json(items) or [] for s in (row.get("serials") or [])}
	ret = _as_system(build)
	_signed_by(ret.name, user)
	if returned:
		from smart_power.sp_stock.warranty import void

		void(
			{"sales_invoice": invoice, "serial_no": ("in", sorted(returned))},
			_("Returned on {0}.").format(ret.name),
		)
	return {"name": ret.name, "refund": abs(flt(ret.grand_total))}


@frappe.whitelist()
def receipt(name: str) -> str:
	"""The receipt's HTML, for the cashier to print."""
	_check()
	if not is_showroom(frappe.get_doc(SI, name)):
		frappe.throw(_("{0} is not a showroom receipt.").format(frappe.bold(name)))
	return _as_system(lambda: frappe.get_print(SI, name, RECEIPT_FORMAT))


@frappe.whitelist()
def find_receipt(name: str) -> dict:
	"""An earlier receipt and what can still be returned of each item."""
	_check()
	name = (name or "").strip()
	if not frappe.db.exists(SI, {"name": name, "naming_series": SERIES, "docstatus": 1, "is_return": 0}):
		frappe.throw(_("No showroom receipt {0}.").format(frappe.bold(name)))
	doc = frappe.get_doc(SI, name)
	left = returnable(doc)
	serials = returnable_serials(doc)
	return {
		"name": doc.name,
		"customer_name": doc.customer_name,
		"posting_date": doc.posting_date,
		"grand_total": flt(doc.grand_total),
		"items": [
			{
				"item_code": r.item_code,
				"item_name": r.item_name,
				"qty": flt(r.qty),
				"rate": flt(r.rate),
				"returnable": left.get(r.item_code, 0),
				"serials": serials.get(r.item_code, []),
			}
			for r in doc.items
		],
	}


def returnable(doc) -> dict[str, float]:
	"""What is left to return of each item of a receipt: sold less what earlier returns took."""
	left = {}
	for r in doc.items:
		left[r.item_code] = left.get(r.item_code, 0) + flt(r.qty)
	for row in frappe.get_all(
		"Sales Invoice Item",
		{"parenttype": SI, "docstatus": 1, "parent": ("in", _returns_of(doc.name) or [""])},
		["item_code", "qty"],
	):
		left[row.item_code] = left.get(row.item_code, 0) - abs(flt(row.qty))
	return {k: max(v, 0) for k, v in left.items()}


def _bundle_serials(bundle: str | None) -> list[str]:
	if not bundle:
		return []
	return frappe.get_all("Serial and Batch Entry", {"parent": bundle}, pluck="serial_no", order_by="idx asc")


def returnable_serials(doc) -> dict[str, list[str]]:
	"""The serials of each item sold on a receipt that no return has taken back yet."""
	sold = {}
	for r in doc.items:
		sold.setdefault(r.item_code, []).extend(_bundle_serials(r.serial_and_batch_bundle))
	for row in frappe.get_all(
		"Sales Invoice Item",
		{"parenttype": SI, "docstatus": 1, "parent": ("in", _returns_of(doc.name) or [""])},
		["item_code", "serial_and_batch_bundle"],
	):
		gone = set(_bundle_serials(row.serial_and_batch_bundle))
		sold[row.item_code] = [s for s in sold.get(row.item_code, []) if s not in gone]
	return {k: v for k, v in sold.items() if v}


def _returns_of(name: str) -> list[str]:
	return frappe.get_all(SI, {"return_against": name, "docstatus": 1}, pluck="name")


@frappe.whitelist()
def today_sales() -> list[dict]:
	_check()
	return frappe.get_all(
		SI,
		filters={"naming_series": SERIES, "posting_date": nowdate(), "docstatus": 1},
		fields=["name", "customer_name", "grand_total", "is_return", "return_against", "owner"],
		order_by="creation desc",
		limit=TODAY_SHOWN,
	)
