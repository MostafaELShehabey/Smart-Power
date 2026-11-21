"""R1 Station financial position (SP-139): the owner's "ميزان الحركة", from the books."""

import frappe
from frappe import _

from smart_power.sp_finance.station_position import check_viewer, rows

NARROW, MONEY, NAME = 90, 125, 170  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	check_viewer()
	return columns(), rows(frappe._dict(filters or {}))


def columns() -> list[dict]:
	money = {"fieldtype": "Currency", "width": MONEY}
	return [
		{
			"fieldname": "station",
			"label": _("Station"),
			"fieldtype": "Link",
			"options": "SP Station",
			"width": NARROW,
		},
		{"fieldname": "customer_name", "label": _("Customer"), "fieldtype": "Data", "width": NAME},
		{"fieldname": "contract_date", "label": _("Contract Date"), "fieldtype": "Date", "width": NARROW},
		{"fieldname": "financing", "label": _("Financing"), "fieldtype": "Data", "width": NARROW},
		{"fieldname": "capacity_kw", "label": _("Capacity (kW)"), "fieldtype": "Float", "width": NARROW},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": NARROW},
		{"fieldname": "agreed", "label": _("Agreed with the Customer"), **money},
		{"fieldname": "estimated_cost", "label": _("Estimated Cost"), **money},
		{"fieldname": "actual_cost", "label": _("Actual Cost"), **money},
		{"fieldname": "owed_to_suppliers", "label": _("Owed to Suppliers"), **money},
		{"fieldname": "paid_to_suppliers", "label": _("Paid to Suppliers"), **money},
		{"fieldname": "remaining_to_suppliers", "label": _("Remaining to Suppliers"), **money},
		{"fieldname": "collected", "label": _("Collected from the Customer"), **money},
		{"fieldname": "cash_position", "label": _("Collected - Owed to Suppliers"), **money},
		{"fieldname": "remaining_from_customer", "label": _("Remaining from the Customer"), **money},
		{"fieldname": "expected_profit", "label": _("Expected Profit"), **money},
		{"fieldname": "profit", "label": _("Profit"), **money},
	]
