"""BUG-26: a station cancelled before the fix still shows its paid, remaining and next due."""

import frappe

from smart_power.sp_stations.money import CANCELLED, STATION, refresh


def execute():
	for station in frappe.get_all(STATION, {"status": CANCELLED}, pluck="name"):
		refresh(station)
