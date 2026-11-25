"""BUG-27: the stations opened before their size was taken from the quote get it now (the plant's
kW and the pump's HP), so the stations list and the installed-capacity statement count them."""

import frappe

from smart_power.sp_stations.station import list_columns, size_from_quote

STATION = "SP Station"


def execute():
	for name in frappe.get_all(STATION, {"capacity_kw_total": 0, "hp_total": 0}, pluck="name"):
		doc = frappe.get_doc(STATION, name)
		if not size_from_quote(doc, doc.quotation_accepted):
			continue
		for row in doc.systems:
			frappe.db.set_value(
				row.doctype, row.name, {"capacity_kw": row.capacity_kw, "hp": row.hp}, update_modified=False
			)
		hp_total, summary = list_columns(doc.systems)
		frappe.db.set_value(
			STATION,
			name,
			{
				"capacity_kw_total": sum((row.capacity_kw or 0) * (row.qty or 1) for row in doc.systems),
				"hp_total": hp_total,
				"systems_summary": summary,
			},
			update_modified=False,
		)
