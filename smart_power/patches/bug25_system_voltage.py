"""BUG-25: the off-grid inverter and batteries follow the battery bank's voltage. The items of the
inverter and battery groups get their system voltage from their names where it is plain (51.2 V is
48, 25.6 V is 24, 12.8 V is 12; a range such as 12/24 V is left for the admin), and the shipped
off-grid template's versions a site already has get the lines' voltage formula."""

import re

import frappe
from frappe.utils import flt
from frappe.utils.nestedset import get_descendants_of

from smart_power.sp_quotes.calc_templates import template_data

GROUPS = ("إنفرترات ودرايفات", "بطاريات")
NOMINAL = {12: 12, 12.8: 12, 24: 24, 25.6: 24, 48: 48, 51.2: 48}
VOLTS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:V|فولت)(?!\s*AC)", re.IGNORECASE)
RANGE = re.compile(r"\d+\s*/\s*\d+\s*(?:V|فولت)", re.IGNORECASE)
TEMPLATE, LINE, FIELD = "SP Calc Template", "SP Calc Template Line", "voltage_formula"


def voltage_in(name: str | None) -> float | None:
	"""The one nominal system voltage a name gives, else None."""
	if not name or RANGE.search(name):
		return None
	found = {NOMINAL.get(flt(v)) for v in VOLTS.findall(name)} - {None}
	return found.pop() if len(found) == 1 else None


def execute():
	if not frappe.db.has_column("Item", "sp_system_voltage"):
		from frappe.utils.fixtures import sync_fixtures

		sync_fixtures("smart_power")
	frappe.reload_doc("sp_quotes", "doctype", "sp_calc_template_line")
	for group in GROUPS:
		if not frappe.db.exists("Item Group", group):
			continue
		groups = [group, *get_descendants_of("Item Group", group)]
		for item in frappe.get_all(
			"Item", {"item_group": ("in", groups)}, ["name", "item_name", "sp_system_voltage"]
		):
			voltage = voltage_in(item.item_name)
			if voltage and not flt(item.sp_system_voltage):
				frappe.db.set_value("Item", item.name, "sp_system_voltage", voltage, update_modified=False)
	data = template_data("offgrid.json")
	shipped = {row["line_key"]: row[FIELD] for row in data["lines"] if row.get(FIELD)}
	for template in frappe.get_all(TEMPLATE, {"template_key": data["template_key"]}, pluck="name"):
		for row in frappe.get_all(
			LINE, {"parent": template, "parenttype": TEMPLATE}, ["name", "line_key", FIELD]
		):
			if shipped.get(row.line_key) and not row.get(FIELD):
				frappe.db.set_value(LINE, row.name, FIELD, shipped[row.line_key], update_modified=False)
