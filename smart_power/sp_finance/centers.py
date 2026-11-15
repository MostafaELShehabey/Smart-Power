"""Financial centers (SP-27; decisions 34-36 and 39-41; tech plan 6-11-2026 section 3 rule 5).

Five cost centers under the company group: Projects, Showroom, Winch, Jumbo and Indirect Pool.
The admin may add children later (that is data, not code). Each source posts to its center,
set in Smart Power Settings > Financial Centers:

    station documents → Projects (with the station's project)
    showroom          → Showroom
    winch / jumbo     → their own center
    salaries, rent, general costs → Indirect Pool (split monthly into stations, SP-124)

A station is never a cost center and there is no Station dimension: its Project (1:1, with a
back-link `sp_station`) tags every GL line, payment and purchase of the station.
"""

import frappe
from frappe import _

from smart_power.constants import SETTINGS_DOCTYPE
from smart_power.sp_core.setup.seed import defaults

PROJECTS, SHOWROOM, WINCH, JUMBO, INDIRECT = "projects", "showroom", "winch", "jumbo", "indirect"


def _spec() -> list[dict]:
	return defaults()["cost_centers"]["centers"]


def seed_centers(company: str) -> dict:
	"""The five centers under the company's group, and the settings map when it is empty."""
	root = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1}, "name", order_by="lft asc")
	if not root:
		frappe.throw(_("Company {0} has no cost center group.").format(company))
	made = {}
	for row in _spec():
		name = frappe.db.get_value(
			"Cost Center", {"company": company, "cost_center_name": row["name"], "is_group": 0}
		)
		if not name:
			doc = frappe.get_doc(
				{
					"doctype": "Cost Center",
					"cost_center_name": row["name"],
					"company": company,
					"parent_cost_center": root,
					"is_group": 0,
				}
			)
			doc.flags.ignore_permissions = True
			doc.insert()
			name = doc.name
		made[row["key"]] = name
	settings = frappe.get_single(SETTINGS_DOCTYPE)
	changed = False
	for key, name in made.items():
		if not settings.get(f"center_{key}"):
			settings.set(f"center_{key}", name)
			changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.save()
	return made


def center(key: str, company: str | None = None) -> str | None:
	"""The cost center a source posts to (Smart Power Settings), else the company's default."""
	from smart_power.sp_core.services.settings import get_value

	name = get_value(f"center_{key}")
	if name and (not company or frappe.get_cached_value("Cost Center", name, "company") == company):
		return name
	return frappe.get_cached_value("Company", company, "cost_center") if company else None


def station_center(company: str | None = None) -> str | None:
	"""Station documents post to Projects (SP-27)."""
	return center(PROJECTS, company)


def tag_project(station) -> None:
	"""The station's project: its back-link and the Projects center (ERPNext defaults from it)."""
	if not station.project:
		return
	frappe.db.set_value(
		"Project",
		station.project,
		{"sp_station": station.name, "cost_center": station_center(station.company)},
		update_modified=False,
	)
