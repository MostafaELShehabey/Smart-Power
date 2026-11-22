"""Station task templates (SP-173): the steps a station of a system type goes through, as data.

An SP Task Template holds, for one system type, its steps: what to do, the role that owns it,
the documents and the expected days. When a station of that type opens, every active user with
the step's role gets the step as an inbox task on the station, due after its expected days when
set. The first template is the on-grid grid-connection (net metering) cycle, shipped as draft
steps for the admin to correct (owner's decision 22-11-2026; the real cycle is still open, SP-158).

    seed_task_templates()   the shipped templates the site does not have yet (never overwritten)
    open_station_tasks(st)  station after_insert: the tasks of its system types' templates
"""

import frappe
from frappe.utils import add_days, cint, now_datetime

from smart_power.sp_core.inbox import create_task
from smart_power.sp_core.services.lists import by_code

TEMPLATE, STATION = "SP Task Template", "SP Station"
SHIPPED = "grid_connection.json"


def seed_task_templates() -> list[str]:
	"""Returns the names of the templates created."""
	path = frappe.get_app_path("smart_power", "sp_stations", SHIPPED)
	created = []
	for data in frappe.get_file_json(path)["templates"]:
		if frappe.db.exists(TEMPLATE, data["template_name"]):
			continue
		system_type = by_code(*data["system_type"])
		if not system_type:
			continue  # before the lists are seeded: a later run makes it
		doc = frappe.get_doc(
			{
				"doctype": TEMPLATE,
				"template_name": data["template_name"],
				"system_type": system_type,
				"task_type": data["task_type"],
				"description": data.get("description"),
				"steps": data["steps"],
			}
		).insert(ignore_permissions=True)
		created.append(doc.name)
	return created


def _users_with(role: str) -> list[str]:
	users = frappe.get_all("Has Role", {"role": role, "parenttype": "User"}, pluck="parent")
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")


def open_station_tasks(station) -> list[str]:
	"""The tasks of the active templates of the station's system types; returns the task names."""
	types = {row.system_type for row in station.get("systems") or [] if row.system_type}
	if not types:
		return []
	names = []
	opened = now_datetime()
	for name in frappe.get_all(
		TEMPLATE, {"system_type": ("in", list(types)), "is_active": 1}, pluck="name", order_by="name asc"
	):
		template = frappe.get_doc(TEMPLATE, name)
		for step in template.steps:
			days = cint(step.expected_days)
			names += create_task(
				template.task_type,
				STATION,
				station.name,
				_users_with(step.owner_role),
				step.subject,
				description=step.documents,
				due_at=add_days(opened, days) if days else None,
				distinct_subject=True,
			)
	return names
