"""Special quote lines (SP-58): manual lines, merge for printing, the winch line, the commission.

    Manual       a free-text line (e.g. transport to a far site): text, qty, cost and sell
    Winch        the winch amount for this station, shown to the customer; on the contract the
                 station gets an expected winch job of that amount (winch income and station cost
                 once it is done; the winch booking itself is E12)
    Commission   the station commission: a lump sum agreed in advance, cost only (sell 0, cost =
                 the amount), never printed; it lowers the quote's profit, not the customer total,
                 and goes to the contract as the station's commission

Any line can carry a Print Group: lines of one group print as one lump-sum line (quote_print).
Each kind has a non-stock service item (defaults.json service_items) so the line reaches the
Sales Order; the line's own text replaces the item name.
"""

import frappe
from frappe.utils import flt
from frappe.utils.nestedset import get_root_of

from smart_power.sp_core.setup.seed import defaults

MANUAL, WINCH, COMMISSION = "Manual", "Winch", "Commission"
UOM = "Nos"


def service_items() -> dict:
	"""{kind: item_code} of the special lines."""
	return {row["kind"]: row["item_code"] for row in defaults()["service_items"]["items"]}


def service_item(kind: str) -> str:
	"""The service item of a line kind, seeded first on a site set up before SP-58 (or a fresh
	test site, where the catalogue setup has not run)."""
	item_code = service_items()[kind]
	if not frappe.db.exists("Item", item_code):
		seed_service_items()
	return item_code


def seed_service_items() -> None:
	"""The service items of the special lines and their item group, where missing."""
	spec = defaults()["service_items"]
	root = get_root_of("Item Group")
	if not root:
		return
	if not frappe.db.exists("Item Group", spec["group"]):
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": spec["group"], "parent_item_group": root}
		).insert(ignore_permissions=True)
	for row in spec["items"]:
		if frappe.db.exists("Item", row["item_code"]):
			continue
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": row["item_code"],
				"item_name": row["item_name"],
				"item_group": spec["group"],
				"stock_uom": UOM,
				"is_stock_item": 0,
				"include_item_in_manufacturing": 0,
			}
		).insert(ignore_permissions=True)


def before_validate(doc, method=None) -> None:
	"""Quotation before_validate: each kind's item, and the commission as a cost-only line."""
	items = service_items()
	kind_of = {code: kind for kind, code in items.items()}
	for row in doc.items:
		if not row.get("sp_line_kind") and row.item_code in kind_of:
			row.sp_line_kind = kind_of[row.item_code]
		kind = row.get("sp_line_kind")
		if not kind:
			row.sp_is_hidden = 0
			continue
		if not row.item_code:
			row.item_code = items.get(kind)
			if row.item_code and not frappe.db.exists("Item", row.item_code):
				seed_service_items()  # a site set up before SP-58, or a fresh test site
		if not row.item_name:
			row.item_name = frappe.db.get_value("Item", row.item_code, "item_name") if row.item_code else kind
		row.uom = row.uom or UOM
		row.conversion_factor = flt(row.conversion_factor) or 1
		row.sp_is_hidden = 1 if kind == COMMISSION else 0
		if kind == COMMISSION:
			# cost only: an amount typed as the sell price is the commission
			if not flt(row.get("sp_cost")) and flt(row.rate):
				row.sp_cost = flt(row.rate)
			row.price_list_rate = row.rate = row.base_rate = 0
			row.discount_percentage = row.discount_amount = row.margin_rate_or_amount = 0
			row.sp_lock_markup = 1


def kind_total(quote, kind: str, cost: bool = False) -> float:
	"""The amount (or, with cost, the cost) of the quote's lines of one kind."""
	return sum(
		flt(r.get("sp_cost")) * flt(r.qty) if cost else flt(r.amount)
		for r in quote.items
		if r.get("sp_line_kind") == kind
	)


@frappe.whitelist()
def get_service_items() -> dict:
	"""For the quote form: the service item of each line kind."""
	frappe.has_permission("Quotation", "read", throw=True)
	return service_items()
