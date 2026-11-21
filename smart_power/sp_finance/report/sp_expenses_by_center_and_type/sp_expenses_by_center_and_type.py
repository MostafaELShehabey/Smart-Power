"""A10 Expenses by center and type (SP-123): submitted expenses, totalled per center and type."""

import frappe
from frappe import _

from smart_power.sp_finance.expenses import expenses_by_center

MONEY, NAME = 130, 180  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	return columns(), expenses_by_center(frappe._dict(filters or {}))


def columns() -> list[dict]:
	return [
		{
			"fieldname": "cost_center",
			"label": _("Cost Center"),
			"fieldtype": "Link",
			"options": "Cost Center",
			"width": NAME,
		},
		{"fieldname": "center_type", "label": _("Center"), "fieldtype": "Data", "width": MONEY},
		{"fieldname": "expense_type", "label": _("Expense Type"), "fieldtype": "Data", "width": NAME},
		{"fieldname": "count", "label": _("Expenses"), "fieldtype": "Int", "width": MONEY},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": MONEY},
	]
