"""AR1 Customer balances (SP-120): one row per station, grouped by customer, with the total.

Each row is the station's money chips (SP-73) plus overdue and Agri Bank advances; the figures
are the station's own, so the totals match the chips. A collection officer sees only their
stations. The Statement link prints the station's statement (SP Customer Statement).
"""

import frappe
from frappe import _

from smart_power.sp_finance.balances import station_rows


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	return columns(), station_rows(filters)


NARROW, MONEY, WIDE, NAME = 110, 130, 150, 180  # sp-allow-number: column widths in pixels


def columns() -> list[dict]:
	money = {"fieldtype": "Currency", "width": MONEY}
	return [
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": NARROW,
		},
		{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": NAME},
		{
			"fieldname": "station",
			"label": _("Station"),
			"fieldtype": "Link",
			"options": "SP Station",
			"width": MONEY,
		},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": NARROW},
		{"fieldname": "agreed", "label": _("Agreed"), **money},
		{"fieldname": "paid", "label": _("Paid"), **money},
		{"fieldname": "pending", "label": _("Pending Confirmation"), **money},
		{"fieldname": "remaining", "label": _("Remaining"), **money},
		{"fieldname": "overdue", "label": _("Overdue"), **money},
		{"fieldname": "advances", "label": _("Advances (Agri Bank)"), **money},
		{"fieldname": "next_due_date", "label": _("Next Due"), "fieldtype": "Date", "width": NARROW},
		{"fieldname": "next_due_amount", "label": _("Next Due Amount"), **money},
		{
			"fieldname": "collection_owner",
			"label": _("Collection Owner"),
			"fieldtype": "Link",
			"options": "User",
			"width": WIDE,
		},
		{"fieldname": "statement", "label": _("Statement"), "fieldtype": "Data", "width": 100},
	]
