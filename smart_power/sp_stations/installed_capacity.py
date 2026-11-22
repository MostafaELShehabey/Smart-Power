"""R3 Installed capacity statement (SP-141): the stations put into operation in a period, in the
layout of the company's own statement (بيان القدرات المركبة), for EgyptERA's semi-annual report.

    rows       a station technically closed (or since financially closed) whose operation date is
               in the period: operation date, station (its main system type), customer, phone,
               location, kW, price per kW (agreed / kW) and the agreed total
    sections   the stations grouped by their main system type (the system line with the most kW),
               in the list's order, each under an ordinal heading (أولاً، ثانياً …)
    total      the count, the total kW and the total value

Filters: the period (default: this half-year), the system type, the company. آية (regulatory
compliance) and the admin see it; it has no cost or profit.

    statement(filters)   the rows: sections and their stations, the total last
"""

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate, nowdate

STATION = "SP Station"
CLOSED = ("Technically closed", "Financially closed")
SYSTEM_TYPE = "System Type"
# the section headings, as in the company's statement
ORDINALS = (
	"Firstly",
	"Secondly",
	"Thirdly",
	"Fourthly",
	"Fifthly",
	"Sixthly",
	"Seventhly",
	"Eighthly",
	"Ninthly",
	"Tenthly",
	"Eleventhly",
	"Twelfthly",
)
MONTHS_IN_HALF = 6  # sp-allow-number: a half-year, EgyptERA's reporting period
SECOND_HALF_MONTH = 7  # sp-allow-number: July opens the second half-year
DATE_FORMAT = "dd/MM/yyyy"  # as on the company's statement
KW_DIGITS, MONEY_DIGITS = 1, 2  # sp-allow-number: kW to one decimal; currency precision


def label(name: str) -> str:
	"""A list value in the user's language (Arabic, else English)."""
	value_ar, value_en = frappe.get_cached_value("SP List Value", name, ["value_ar", "value_en"]) or (
		None,
		None,
	)
	arabic = (frappe.local.lang or "").startswith("ar")
	return (value_ar if arabic else value_en) or value_ar or value_en or name


def half_year(on=None) -> tuple:
	"""The half-year a date falls in: January to June, or July to December."""
	on = getdate(on or nowdate())
	first = SECOND_HALF_MONTH if on.month >= SECOND_HALF_MONTH else 1
	start = on.replace(month=first, day=1)
	end = start.replace(month=first + MONTHS_IN_HALF - 1)
	return start, frappe.utils.get_last_day(end)


def _filters(filters) -> frappe._dict:
	filters = frappe._dict(filters or {})
	start, end = half_year()
	filters.from_date = getdate(filters.get("from_date") or start)
	filters.to_date = getdate(filters.get("to_date") or end)
	if filters.from_date > filters.to_date:
		frappe.throw(_("The from date is after the to date."))
	return filters


def _main_system(systems: list) -> str | None:
	"""The system line with the most kW (a station's main system)."""
	if not systems:
		return None
	return max(systems, key=lambda s: flt(s.capacity_kw) * (flt(s.qty) or 1)).system_type


def _location(station) -> str:
	parts = [label(station.region) if station.region else "", (station.location_text or "").splitlines()]
	place = parts[1][0].strip() if parts[1] else ""
	return " - ".join(p for p in (parts[0], place) if p)


def stations(filters) -> list:
	conditions = {
		"status": ("in", CLOSED),
		"operation_date": ("between", [filters.from_date, filters.to_date]),
	}
	if filters.get("company"):
		conditions["company"] = filters.company
	rows = frappe.get_all(
		STATION,
		conditions,
		[
			"name",
			"operation_date",
			"customer",
			"customer_name",
			"region",
			"location_text",
			"capacity_kw_total",
			"agreed_amount",
		],
		order_by="operation_date asc, name asc",
	)
	systems: dict = {}
	for line in frappe.get_all(
		"SP Station System",
		{"parenttype": STATION, "parent": ("in", [r.name for r in rows] or [""])},
		["parent", "system_type", "capacity_kw", "qty"],
	):
		systems.setdefault(line.parent, []).append(line)
	phones = dict(
		frappe.get_all(
			"Customer",
			{"name": ("in", list({r.customer for r in rows if r.customer}) or [""])},
			["name", "sp_mobile"],
			as_list=True,
		)
	)
	for r in rows:
		r.system_type = _main_system(systems.get(r.name, []))
		r.phone = phones.get(r.customer) or ""
	if filters.get("system_type"):
		rows = [r for r in rows if filters.system_type in {s.system_type for s in systems.get(r.name, [])}]
	return rows


def _row(station) -> dict:
	kw = flt(station.capacity_kw_total, KW_DIGITS)
	total = flt(station.agreed_amount, MONEY_DIGITS)
	return {
		"operation_date": formatdate(station.operation_date, DATE_FORMAT),
		"station": label(station.system_type) if station.system_type else _("Not set"),
		"customer_name": station.customer_name,
		"phone": station.phone,
		"location": _location(station),
		"capacity_kw": kw,
		"price_per_kw": flt(total / kw, MONEY_DIGITS) if kw else 0.0,
		"total": total,
		"station_name": station.name,
	}


def _order() -> dict:
	"""System type → its place in the list (the sections' order)."""
	return {
		r.name: r.sort_order
		for r in frappe.get_all("SP List Value", {"list_name": SYSTEM_TYPE}, ["name", "sort_order"])
	}


def statement(filters=None) -> list[dict]:
	filters = _filters(filters)
	found = stations(filters)
	groups: dict = {}
	for s in found:
		groups.setdefault(s.system_type, []).append(s)
	order = _order()
	out = []
	for i, system_type in enumerate(sorted(groups, key=lambda k: (k is None, order.get(k, 0), k or ""))):
		ordinal = _(ORDINALS[i]) if i < len(ORDINALS) else str(i + 1)
		name = label(system_type) if system_type else _("Not set")
		out.append(
			{"operation_date": _("{0}: {1} stations").format(ordinal, name), "is_section": 1, "indent": 0}
		)
		out += [{**_row(s), "indent": 1} for s in groups[system_type]]
	out.append(
		{
			"operation_date": _("Grand total"),
			"station": _("{0} stations").format(len(found)),
			"capacity_kw": flt(sum(flt(s.capacity_kw_total) for s in found), KW_DIGITS),
			"total": flt(sum(flt(s.agreed_amount) for s in found), MONEY_DIGITS),
			"count": len(found),
			"is_total": 1,
			"indent": 0,
		}
	)
	return out
