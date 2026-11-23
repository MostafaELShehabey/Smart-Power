"""SP-183: the calibration report's minimum stations from the seed, and the shipped templates'
calibration sources on the versions a site already has (installation from the site labour,
transport from the winch and transport, the per-string lines' inputs)."""

import frappe

from smart_power.sp_core.setup.seed import defaults
from smart_power.sp_quotes.calc_templates import FILES, template_data

SETTINGS, TEMPLATE, LINE = "Smart Power Settings", "SP Calc Template", "SP Calc Template Line"
FIELDS = ("calibration_source", "calibration_input")


def execute():
	frappe.reload_doc("sp_quotes", "doctype", "sp_calc_template_line")
	frappe.reload_doc("sp_core", "doctype", "smart_power_settings")
	if not frappe.db.get_single_value(SETTINGS, "calibration_min_stations"):
		value = defaults()["settings"]["calibration_min_stations"]["value"]
		frappe.db.set_single_value(SETTINGS, "calibration_min_stations", value)
	for file_name in FILES:
		data = template_data(file_name)
		shipped = {row["line_key"]: row for row in data["lines"] if any(row.get(f) for f in FIELDS)}
		for template in frappe.get_all(TEMPLATE, {"template_key": data["template_key"]}, pluck="name"):
			inputs = set(
				frappe.get_all(
					"SP Calc Template Input", {"parent": template, "parenttype": TEMPLATE}, pluck="input_key"
				)
			)
			for row in frappe.get_all(
				LINE, {"parent": template, "parenttype": TEMPLATE}, ["name", "line_key", *FIELDS]
			):
				line = shipped.get(row.line_key) or {}
				values = {
					f: line[f]
					for f in FIELDS
					if line.get(f) and not row.get(f) and (f != "calibration_input" or line[f] in inputs)
				}
				if values:
					frappe.db.set_value(LINE, row.name, values, update_modified=False)
