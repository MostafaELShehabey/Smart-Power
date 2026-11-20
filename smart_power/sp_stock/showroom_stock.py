"""Showroom stock low (SP-87): the items of the showroom store at or under their reorder level
(the Item's Reorder table, one row per warehouse), on the showroom home card and in a daily alert.

    low_items(company)       the showroom store's rows at or under their level
    check_showroom_stock()   daily: the showroom store keepers hear how many items are low
"""

import frappe
from frappe import _

from smart_power.notify import send
from smart_power.sp_stock.stock_by_owner import stock_rows
from smart_power.sp_stock.warehouses import SHOWROOM

EVENT_LOW = "showroom_stock_low"
ALERTED_ROLE = "SP Showroom Store Keeper"
REPORT = "SP Stock by Owner"
NAMED = 3  # sp-allow-number: the alert names the first three items


def showroom_stores(company: str | None = None) -> list[str]:
	filters = {"warehouse_type": SHOWROOM, "is_group": 0, "disabled": 0}
	if company:
		filters["company"] = company
	return frappe.get_all("Warehouse", filters, pluck="name")


def low_items(company: str | None = None) -> list[dict]:
	rows = []
	for store in showroom_stores(company):
		rows += stock_rows({"location": store, "below_reorder": 1, "owner": "company"})
	return rows


def check_showroom_stock() -> int:
	"""Daily: one alert to the showroom store keepers while items are low."""
	from smart_power.sp_sales.quote_request import _users_with

	rows = low_items()
	users = _users_with(ALERTED_ROLE)
	if rows and users:
		names = ", ".join(r["item_name"] or r["item_code"] for r in rows[:NAMED])
		if len(rows) > NAMED:
			names = _("{0} and {1} more").format(names, len(rows) - NAMED)
		send(
			EVENT_LOW,
			users,
			None,
			None,
			_("{0} items low in the showroom store: {1}").format(len(rows), names),
			from_user="Administrator",
		)
	return len(rows)
