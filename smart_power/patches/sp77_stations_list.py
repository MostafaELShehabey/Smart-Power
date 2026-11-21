"""SP-77: the stations list's views (Open, Installing, Collecting, Overdue, Closed) and its
Systems and HP columns for the stations already open."""

import json

import frappe

from smart_power.lists import VIEW, seed_list_views
from smart_power.sp_stations.setup import seed_list_settings
from smart_power.sp_stations.station import list_columns

STATION = "SP Station"
# the SP-45 tab the S1 views replace, as the seed made it
OLD_OPEN = ("Still Open", [["status", "not in", ["Financially closed", "Cancelled"]]])
ORDER = {"Mine": 1, "Overdue": 5, "All": 7}


def execute():
	frappe.reload_doc("sp_stations", "doctype", "sp_station")
	for name in frappe.get_all(STATION, pluck="name"):
		doc = frappe.get_doc(STATION, name)
		hp, systems = list_columns(doc.systems)
		frappe.db.set_value(
			STATION, name, {"hp_total": hp, "systems_summary": systems}, update_modified=False
		)
	label, filters = OLD_OPEN
	old = frappe.db.get_value(
		VIEW, {"list_doctype": STATION, "label": label}, ["name", "filters"], as_dict=True
	)
	if old and json.loads(old.filters or "[]") == filters:  # left as seeded: Open replaces it
		frappe.db.set_value(VIEW, old.name, "is_active", 0)
	for label, order in ORDER.items():
		frappe.db.set_value(VIEW, {"list_doctype": STATION, "label": label}, "sort_order", order)
	seed_list_views()
	seed_list_settings()
