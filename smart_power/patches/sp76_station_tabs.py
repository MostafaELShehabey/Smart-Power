"""SP-76: the station record's tabs by role (the seed, where the admin has not set them), and
the station's amounts on permlevel 1 for the roles that see money."""

import frappe

from smart_power.sp_stations.station_tabs import seed_tab_access


def execute():
	frappe.reload_doc("sp_stations", "doctype", "sp_station_tab_access")
	frappe.reload_doc("sp_core", "doctype", "smart_power_settings")
	frappe.reload_doc("sp_stations", "doctype", "sp_station")
	seed_tab_access()
	_money_permlevel_on_customised_roles()


def _money_permlevel_on_customised_roles() -> None:
	"""Where the admin customised the station's role permissions, the DocType's own rows no
	longer apply: give permlevel 1 to each role that reads the station there, except the site's."""
	from frappe.permissions import add_permission, update_permission_property

	station = "SP Station"
	if not frappe.db.exists("Custom DocPerm", {"parent": station}):
		return
	writers = ("System Manager", "SP Admin", "SP Project Manager")
	readers = frappe.get_all(
		"Custom DocPerm", {"parent": station, "permlevel": 0, "read": 1}, pluck="role", distinct=True
	)
	for role in readers:
		if role == "SP Installation Manager":
			continue
		if not frappe.db.exists("Custom DocPerm", {"parent": station, "role": role, "permlevel": 1}):
			add_permission(station, role, 1)
			if role in writers:
				update_permission_property(station, role, 1, "write", 1, validate=False)
	frappe.clear_cache(doctype=station)
