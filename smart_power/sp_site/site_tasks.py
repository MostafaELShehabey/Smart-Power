"""S2 Site task board and TK1 My site tasks (SP-100).

A site task is an ERPNext Task on the station's Project, with the station, the site stage, the
check-in (time and location) and the hours on site (custom fields).

    plan(station, title, technicians, planned_date, stage)   the planners (projects manager,
                                              installation manager, admin) give the crew a task
    my_tasks()                                the technician's open site tasks (TK1)
    check_in(task, lat, lng)                  on site: the time and the location; In progress
    mark_done(task, hours)                    Done, with the hours; photos are the task's attachments
    board(station)                            the station's tasks: To do · In progress · Done

Hours are for the labour view only: cost is posted by the site daily log (SP-96), never from a
task, so nothing is counted twice.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_fullname, getdate, now_datetime, today

TASK, STATION = "Task", "SP Station"
PLANNER_ROLES = ("SP Project Manager", "SP Installation Manager", "SP Admin", "System Manager")
CREW_ROLES = ("SP Installation Technician", "SP Installation Manager")
OPEN, WORKING, COMPLETED, CANCELLED = "Open", "Working", "Completed", "Cancelled"
COLUMNS = {OPEN: "To do", WORKING: "In progress", COMPLETED: "Done"}
STAGE_LIST = "Site Stage"
NO_LOCATION = "Location not available"


def is_planner(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(PLANNER_ROLES) & set(frappe.get_roles(user)))


@frappe.whitelist()
def technicians(txt: str | None = None) -> list[dict]:
	"""Who a planner can give a site task to: the installation crew, by name."""
	if not is_planner():
		frappe.throw(_("Only a planner gives out site tasks."), frappe.PermissionError)
	holders = frappe.get_all("Has Role", {"role": ("in", CREW_ROLES), "parenttype": "User"}, pluck="parent")
	users = frappe.get_all(
		"User",
		{"name": ("in", holders or [""]), "enabled": 1},
		["name", "full_name"],
		order_by="full_name asc",
	)
	needle = (txt or "").strip().lower()
	return [
		{"value": u.name, "label": u.full_name or u.name, "description": u.name}
		for u in users
		if not needle or needle in (u.full_name or "").lower() or needle in u.name.lower()
	]


def _assigned(task: str) -> list[str]:
	"""The task's technicians: its to-dos, open or closed (a done task's assignments are closed)."""
	return sorted(
		set(frappe.get_all("ToDo", {"reference_type": TASK, "reference_name": task}, pluck="allocated_to"))
	)


def _mine(task: str):
	"""The site task, for one of its technicians (or a planner)."""
	doc = frappe.get_doc(TASK, task)
	if not doc.get("sp_station"):
		frappe.throw(_("{0} is not a site task.").format(task))
	if frappe.session.user not in _assigned(task) and not is_planner():
		frappe.throw(_("This site task is not assigned to you."), frappe.PermissionError)
	return doc


@frappe.whitelist(methods=["POST"])
def plan(
	station: str,
	title: str,
	technicians: list | str,
	planned_date: str | None = None,
	stage: str | None = None,
) -> str:
	"""Give the crew a task on a station."""
	from frappe.desk.form.assign_to import add

	if not is_planner():
		frappe.throw(_("Only the projects or installation manager plans site tasks."), frappe.PermissionError)
	technicians = frappe.parse_json(technicians) if isinstance(technicians, str) else list(technicians or [])
	if not technicians:
		frappe.throw(_("Choose who does the task."))
	project = frappe.db.get_value(STATION, station, "project")
	if not project:
		frappe.throw(_("Station {0} has no project.").format(station))
	if stage and frappe.db.get_value("SP List Value", stage, "list_name") != STAGE_LIST:
		frappe.throw(_("{0} is not a site stage.").format(stage))
	day = planned_date or today()
	doc = frappe.get_doc(
		{
			"doctype": TASK,
			"subject": title,
			"project": project,
			"sp_station": station,
			"sp_stage": stage,
			"exp_start_date": day,
			"exp_end_date": day,
			"status": OPEN,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	add({"doctype": TASK, "name": doc.name, "assign_to": technicians})
	return doc.name


def _row(t) -> dict:
	assigned = _assigned(t.name)
	return {
		"name": t.name,
		"subject": t.subject,
		"station": t.sp_station,
		"stage": frappe.db.get_value("SP List Value", t.sp_stage, "value_ar") if t.sp_stage else None,
		"column": COLUMNS.get(t.status, t.status),
		"status": t.status,
		"planned_date": getdate(t.exp_start_date) if t.exp_start_date else None,
		"technicians": "، ".join(get_fullname(u) for u in assigned),
		"checkin_at": t.sp_checkin_at,
		"checkin_geo": t.sp_checkin_geo,
		"hours": flt(t.sp_hours),
		"photos": frappe.db.count("File", {"attached_to_doctype": TASK, "attached_to_name": t.name}),
	}


FIELDS = [
	"name",
	"subject",
	"status",
	"sp_station",
	"sp_stage",
	"exp_start_date",
	"sp_checkin_at",
	"sp_checkin_geo",
	"sp_hours",
	"_assign",
]


def board(station: str) -> list[dict]:
	"""The station's site tasks, in board order: To do, In progress, Done."""
	rows = frappe.get_all(
		TASK,
		{"sp_station": station, "status": ("in", tuple(COLUMNS))},
		FIELDS,
		order_by="exp_start_date asc, creation asc",
	)
	order = list(COLUMNS)
	return [_row(t) for t in sorted(rows, key=lambda t: order.index(t.status))]


@frappe.whitelist()
def my_tasks() -> list[dict]:
	"""TK1: my open site tasks, the earliest first."""
	user = frappe.session.user
	rows = frappe.get_all(
		TASK,
		{"sp_station": ("is", "set"), "status": ("in", (OPEN, WORKING)), "_assign": ("like", f'%"{user}"%')},
		FIELDS,
		order_by="exp_start_date asc, creation asc",
	)
	return [_row(t) for t in rows]


@frappe.whitelist(methods=["POST"])
def check_in(task: str, lat: float | None = None, lng: float | None = None) -> dict:
	"""On site: the time, and the location when the phone gives one."""
	doc = _mine(task)
	if doc.status == COMPLETED:
		frappe.throw(_("The task is done."))
	doc.sp_checkin_at = now_datetime()
	doc.sp_checkin_geo = (
		f"{flt(lat)},{flt(lng)}" if lat not in (None, "") and lng not in (None, "") else _(NO_LOCATION)
	)
	doc.status = WORKING
	doc.flags.ignore_permissions = True
	doc.save()
	return {"checkin_at": doc.sp_checkin_at, "checkin_geo": doc.sp_checkin_geo}


@frappe.whitelist(methods=["POST"])
def mark_done(task: str, hours: float | None = None) -> str:
	"""The task is done; its hours are kept for the labour view."""
	doc = _mine(task)
	if flt(hours) < 0:
		frappe.throw(_("The hours cannot be negative."))
	if hours not in (None, ""):
		doc.sp_hours = flt(hours)
	doc.status = COMPLETED
	doc.completed_on = today()
	doc.completed_by = frappe.session.user
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.status
