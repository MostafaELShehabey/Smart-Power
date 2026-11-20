"""I3 Stock by location and owner (SP-87). The rows are in smart_power.sp_stock.stock_by_owner; the
value column is there only for those who may see cost (store keepers see quantities only)."""

import frappe
from frappe import _

from smart_power.permissions import can_see_cost
from smart_power.sp_stock.stock_by_owner import stock_rows

NARROW, QTY, WIDE, NAME = 110, 100, 170, 200  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	return columns(), stock_rows(filters)


def columns() -> list[dict]:
	qty = {"fieldtype": "Float", "width": QTY}
	cols = [
		{
			"fieldname": "item_code",
			"label": _("Item Code"),
			"fieldtype": "Link",
			"options": "Item",
			"width": WIDE,
		},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": NAME},
		{"fieldname": "location", "label": _("Stock Location"), "fieldtype": "Data", "width": WIDE},
		{"fieldname": "location_type", "label": _("Location Type"), "fieldtype": "Data", "width": NARROW},
		{"fieldname": "owner", "label": _("Stock Owner"), "fieldtype": "Data", "width": WIDE},
		{"fieldname": "on_hand", "label": _("On Hand"), **qty},
		{"fieldname": "reserved", "label": _("Reserved"), **qty},
		{"fieldname": "available", "label": _("Available"), **qty},
		{"fieldname": "reorder_level", "label": _("Reorder Level"), **qty},
	]
	if can_see_cost():
		cols.append({"fieldname": "value", "label": _("Value"), "fieldtype": "Currency", "width": WIDE})
	cols.append({"fieldname": "history", "label": _("Movements"), "fieldtype": "Data", "width": NARROW})
	return cols
