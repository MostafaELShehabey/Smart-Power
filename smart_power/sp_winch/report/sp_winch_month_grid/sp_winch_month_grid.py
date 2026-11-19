"""W2 month grid (SP-111): the vehicle's month in the winch sheet's own columns, an الاجمالي row
at the foot, and the sheet's closing figures as the summary. The arithmetic is in
smart_power.sp_winch.month_grid; Excel comes out of the standard export in this same order."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from smart_power.sp_winch.month_grid import month_rows, month_totals

NARROW, MONEY, ITEM = 95, 120, 260  # sp-allow-number: column widths in pixels
CARD_SLOT = 3  # sp-allow-number: the collection rate sits before the uncollected card
SUMMED = ("agreed", "paid", "wages", "running", "deposited", "sp_jobs", "sp_expenses", "discount")


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	today = nowdate()
	vehicle = filters.vehicle
	year = int(filters.year or today[:4])
	month = int(filters.month or today[5:7])
	if not vehicle:
		frappe.throw(_("Choose the vehicle."))
	rows = month_rows(vehicle, year, month)
	totals = month_totals(vehicle, year, month)
	rows.append({"item": _("Total"), **{f: totals[f] for f in SUMMED}, "balance": totals["balance"]})
	return columns(), rows, None, None, summary(totals)


def columns() -> list[dict]:
	money = {"fieldtype": "Currency", "width": MONEY}
	return [
		{"fieldname": "work_date", "label": _("Date"), "fieldtype": "Date", "width": NARROW},
		{"fieldname": "item", "label": _("Sheet Item"), "fieldtype": "Data", "width": ITEM},
		{"fieldname": "days", "label": _("Worker Days"), "fieldtype": "Float", "width": NARROW},
		{"fieldname": "agreed", "label": _("Agreed with the Customer"), **money},
		{"fieldname": "paid", "label": _("Paid by the Customer"), **money},
		{"fieldname": "wages", "label": _("Wages and Salaries"), **money},
		{"fieldname": "running", "label": _("Fuel, Oil and Maintenance"), **money},
		{"fieldname": "deposited", "label": _("Handed In"), **money},
		{"fieldname": "balance", "label": _("Balance with the Operator"), **money},
		{"fieldname": "sp_jobs", "label": _("Smart Power Jobs"), **money},
		{"fieldname": "sp_expenses", "label": _("Smart Power Expenses"), **money},
		{"fieldname": "discount", "label": _("Discount"), **money},
		{"fieldname": "note", "label": _("Note"), "fieldtype": "Data", "width": ITEM},
		{
			"fieldname": "entry",
			"label": _("Entry"),
			"fieldtype": "Link",
			"options": "SP Field Entry",
			"width": NARROW,
		},
		{
			"fieldname": "salary",
			"label": _("Crew Salary"),
			"fieldtype": "Link",
			"options": "SP Crew Salary",
			"width": NARROW,
		},
	]


def summary(totals: dict) -> list[dict]:
	cards = [
		{"label": _("Month Revenue"), "value": totals["revenue"], "datatype": "Currency"},
		{"label": _("Month Costs"), "value": totals["costs"], "datatype": "Currency"},
		{
			"label": _("Net Profit"),
			"value": totals["net"],
			"datatype": "Currency",
			"indicator": "Green" if flt(totals["net"]) >= 0 else "Red",
		},
		{"label": _("Uncollected"), "value": totals["uncollected"], "datatype": "Currency"},
		{"label": _("Discounts Given"), "value": -flt(totals["discount"]), "datatype": "Currency"},
	]
	if totals["collection_rate"] is not None:
		rate = flt(totals["collection_rate"]) * 100  # sp-allow-number: shown as a percentage
		cards.insert(CARD_SLOT, {"label": _("Collection Rate"), "value": f"{rate:.0f}%", "datatype": "Data"})
	return cards
