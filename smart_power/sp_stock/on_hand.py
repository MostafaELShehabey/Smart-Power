"""Stock on hand for a quote's picks (SP-57, SP-168): the company's stores, and the supplier's
consignment containers, which stay outside the stock ledger (SP-91)."""

import frappe
from frappe.utils import flt

from smart_power.sp_stock.consignment import CONTAINER, EMPTY
from smart_power.sp_stock.warehouses import company_stores


def on_hand(item_codes, company: str | None = None) -> dict:
	"""{item: {company, consignment}} for each item."""
	codes = list(set(item_codes))
	stock = {code: {"company": 0.0, "consignment": 0.0} for code in codes}
	if not codes:
		return stock
	stores = company_stores(company)
	if stores:
		for row in frappe.get_all(
			"Bin", {"item_code": ("in", codes), "warehouse": ("in", stores)}, ["item_code", "actual_qty"]
		):
			stock[row.item_code]["company"] += flt(row.actual_qty)
	for box in frappe.get_all(
		CONTAINER, {"item": ("in", codes), "status": ("!=", EMPTY)}, ["item", "available_qty"]
	):
		stock[box.item]["consignment"] += flt(box.available_qty)
	return stock
