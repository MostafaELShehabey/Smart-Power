"""The year summary (SP-111): twelve months of the vehicle's key figures, as the sheet's year tab
lays them out, with the الاجمالي line at the foot. Each month is the month grid's closing block."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from smart_power.sp_winch.month_grid import month_totals

MONTHS_IN_YEAR = 12  # sp-allow-number: the year tab's twelve rows
NARROW, MONEY = 110, 125  # sp-allow-number: column widths in pixels
SUMMED = ("agreed", "paid", "wages", "running", "deposited", "sp_jobs", "revenue", "costs", "net")
MONTH_NAMES = (
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
)


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	vehicle = filters.vehicle
	year = int(filters.year or nowdate()[:4])
	if not vehicle:
		frappe.throw(_("Choose the vehicle."))
	rows = []
	for month in range(1, MONTHS_IN_YEAR + 1):
		totals = month_totals(vehicle, year, month)
		rows.append({"month": _(MONTH_NAMES[month - 1]), "month_number": month, **totals})
	total = {field: sum(flt(r.get(field)) for r in rows) for field in SUMMED}
	rows.append({"month": _("Total"), **total, "balance": rows[-1]["balance"]})
	return columns(), rows


def columns() -> list[dict]:
	money = {"fieldtype": "Currency", "width": MONEY}
	return [
		{"fieldname": "month", "label": _("Month"), "fieldtype": "Data", "width": NARROW},
		{"fieldname": "agreed", "label": _("Agreed with the Customer"), **money},
		{"fieldname": "paid", "label": _("Paid by the Customer"), **money},
		{"fieldname": "wages", "label": _("Wages and Salaries"), **money},
		{"fieldname": "running", "label": _("Fuel, Oil and Maintenance"), **money},
		{"fieldname": "deposited", "label": _("Handed In"), **money},
		{"fieldname": "balance", "label": _("Closing Balance"), **money},
		{"fieldname": "sp_jobs", "label": _("Smart Power Jobs"), **money},
		{"fieldname": "revenue", "label": _("Month Revenue"), **money},
		{"fieldname": "costs", "label": _("Month Costs"), **money},
		{"fieldname": "net", "label": _("Net Profit"), **money},
	]
