"""Referrer commissions (SP-177): per referrer, the commission agreed on their stations, what is
posted as owed to them, what is paid, and the balance."""

import frappe
from frappe import _

from smart_power.sp_stations.commission import referrers


def execute(filters: dict | None = None):
	return columns(), referrers(frappe._dict(filters or {}))


NARROW, MONEY, NAME = 90, 130, 180  # sp-allow-number: column widths in pixels


def columns() -> list[dict]:
	money = {"fieldtype": "Currency", "width": MONEY}
	return [
		{
			"fieldname": "referrer",
			"label": _("Referrer"),
			"fieldtype": "Link",
			"options": "Sales Partner",
			"width": NAME,
		},
		{"fieldname": "mobile", "label": _("Mobile"), "fieldtype": "Data", "width": MONEY},
		{"fieldname": "stations", "label": _("Stations"), "fieldtype": "Int", "width": NARROW},
		{"fieldname": "agreed", "label": _("Agreed"), **money},
		{"fieldname": "posted", "label": _("Posted"), **money},
		{"fieldname": "paid", "label": _("Paid"), **money},
		{"fieldname": "balance", "label": _("Balance Owed"), **money},
		{"fieldname": "not_posted", "label": _("Not Posted Yet"), **money},
	]
