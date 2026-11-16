"""Employees and daily workers (SP-33; ERD 7.5: ERPNext Employee, no separate worker DocType).

- Staff are Employees linked to their User (user_id) when they log in.
- A daily worker is an Employee with Daily Worker ticked: name, mobile, daily wage and skill; no
  login, and no birth date or gender needed (Property Setters).
- A crew or wage line (the site daily log, field entries) starts with the worker's daily wage and
  can be changed on the line: crew_line(employee).
- The pickers list active people only (worker_query); a worker set Inactive or Left disappears
  from them, while the lines that already name him keep showing him.
- workers_bundle() is what the mobile app caches for offline use (E16).
"""

import frappe
from frappe import _
from frappe.utils import flt

EMPLOYEE, ACTIVE = "Employee", "Active"
# who picks crew on site logs, winch jobs and field entries (they may not read HR's Employee list)
CREW_ROLES = (
	"System Manager",
	"SP Admin",
	"SP Project Manager",
	"SP Installation Manager",
	"SP Installation Technician",
	"SP Winch Manager",
	"SP Accountant",
)


def _check_crew_role() -> None:
	if frappe.session.user != "Administrator" and not set(CREW_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("You do not pick crew."), frappe.PermissionError)


def validate(doc, method=None) -> None:
	"""Employee validate: a daily worker has a daily wage and no login."""
	if not doc.get("sp_is_daily_worker"):
		return
	if flt(doc.get("sp_daily_wage")) <= 0:
		frappe.throw(_("Enter the daily wage of {0}.").format(doc.employee_name or doc.first_name))
	if doc.get("user_id"):
		frappe.throw(_("A daily worker has no login; untick Daily Worker for staff who sign in."))


@frappe.whitelist()
def crew_line(employee: str) -> dict:
	"""What a new crew or wage line starts with: the worker and his daily wage."""
	_check_crew_role()
	row = frappe.db.get_value(
		EMPLOYEE, employee, ["name", "employee_name", "sp_daily_wage", "sp_skill", "status"], as_dict=True
	)
	if not row:
		frappe.throw(_("Employee {0} not found.").format(employee))
	return {
		"employee": row.name,
		"employee_name": row.employee_name,
		"wage": flt(row.sp_daily_wage),
		"skill": row.sp_skill,
		"active": row.status == ACTIVE,
	}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def worker_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | None
) -> list:
	"""Link query for crew pickers: active people only, by name or mobile; daily workers first."""
	_check_crew_role()
	conditions = {"status": ACTIVE}
	if (filters or {}).get("daily_only"):
		conditions["sp_is_daily_worker"] = 1
	or_filters = {
		"employee_name": ("like", f"%{txt}%"),
		"cell_number": ("like", f"%{txt}%"),
		"name": ("like", f"%{txt}%"),
	}
	rows = frappe.get_all(
		EMPLOYEE,
		filters=conditions,
		or_filters=or_filters,
		fields=["name", "employee_name", "cell_number", "sp_daily_wage"],
		order_by="sp_is_daily_worker desc, employee_name asc",
		start=start,
		page_length=page_len,
	)
	return [
		[r.name, r.employee_name, r.cell_number or "", frappe.format(r.sp_daily_wage, "Currency")]
		for r in rows
	]


@frappe.whitelist()
def workers_bundle() -> list[dict]:
	"""The active people the mobile app keeps offline: name, mobile, skill and daily wage."""
	_check_crew_role()
	return frappe.get_all(
		EMPLOYEE,
		filters={"status": ACTIVE},
		fields=[
			"name",
			"employee_name",
			"cell_number",
			"sp_is_daily_worker",
			"sp_daily_wage",
			"sp_skill",
			"user_id",
		],
		order_by="employee_name asc",
	)
