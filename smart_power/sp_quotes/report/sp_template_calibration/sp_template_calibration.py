"""Calibration report (SP-183): a template's defaults against the closed stations' actuals."""

import frappe
from frappe import _

from smart_power.sp_quotes.calibration import allowed, report

WIDE, MID, NARROW = 220, 140, 110  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	allowed()
	filters = frappe._dict(filters or {})
	if not filters.template:
		return columns(), []
	result = report(filters.template, filters.from_date, filters.to_date)
	rows = [{**r, "source": _(r["source"])} for r in result["lines"]]
	message = _("{0} closed stations in the period used a version of this template.").format(
		len(result["stations"])
	)
	return columns(), rows, message


def columns() -> list[dict]:
	def col(fieldname, label, fieldtype="Float", width=NARROW):
		return {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "width": width}

	return [
		col("description", _("Line"), "Data", WIDE),
		col("source", _("Calibration Source"), "Data", MID),
		col("stations", _("Stations"), "Int"),
		col("est_qty", _("Estimated Qty")),
		col("act_qty", _("Actual Qty")),
		col("qty_deviation", _("Qty Deviation %"), "Percent"),
		col("est_cost", _("Estimated Cost"), "Currency", MID),
		col("act_cost", _("Actual Cost"), "Currency", MID),
		col("cost_deviation", _("Cost Deviation %"), "Percent"),
		col("input", _("Calibrated Input"), "Data", MID),
		col("input_default", _("Current Default")),
		col("suggested_input", _("Suggested Default")),
		col("cost_default", _("Current Unit Cost"), "Currency", MID),
		col("suggested_cost", _("Suggested Unit Cost"), "Currency", MID),
		col("note", _("Note"), "Data", WIDE),
	]
