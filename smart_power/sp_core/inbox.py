"""The task inbox service (SP-39, G3): one inbox instead of WhatsApp groups.

    create_task(task_type, reference_doctype, reference_name, users, subject, ...)
    close_tasks(reference_doctype, reference_name, task_type=None)

Each module makes its tasks through these when something needs a person (a payment to confirm,
a settlement to approve, a password to reset ...) and closes them when it is done. A task can be
snoozed until a date and time; the hourly job brings it back. Every change reaches the assignee's
open inbox at once (realtime "sp_tasks").
"""

import frappe
from frappe.utils import get_datetime, now_datetime

TASK = "SP Task"
OPEN, DONE, CANCELLED = "Open", "Done", "Cancelled"
NORMAL, HIGH = "Normal", "High"
REALTIME_EVENT = "sp_tasks"


def create_task(
	task_type: str,
	reference_doctype: str | None,
	reference_name: str | None,
	users,
	subject: str,
	*,
	description: str | None = None,
	amount: float | None = None,
	image: str | None = None,
	due_at=None,
	priority: str = NORMAL,
) -> list[str]:
	"""One open task per user (a user who already has this open task is not given another)."""
	if isinstance(users, str):
		users = [users]
	names = []
	for user in sorted({u for u in users or [] if u}):
		if reference_name and frappe.db.exists(
			TASK,
			{
				"task_type": task_type,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"assigned_to": user,
				"status": OPEN,
			},
		):
			continue
		doc = frappe.get_doc(
			{
				"doctype": TASK,
				"task_type": task_type,
				"subject": subject,
				"assigned_to": user,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"description": description,
				"amount": amount,
				"image": image,
				"due_at": due_at,
				"priority": priority,
			}
		).insert(ignore_permissions=True)
		names.append(doc.name)
	return names


def close_tasks(
	reference_doctype: str, reference_name: str, task_type: str | None = None, status: str = DONE
) -> list[str]:
	"""Close the open tasks of a record (of one type, if given); returns the closed tasks."""
	filters = {"reference_doctype": reference_doctype, "reference_name": reference_name, "status": OPEN}
	if task_type:
		filters["task_type"] = task_type
	names = frappe.get_all(TASK, filters, pluck="name")
	for name in names:
		frappe.db.set_value(
			TASK,
			name,
			{"status": status, "completed_by": frappe.session.user, "completed_on": now_datetime()},
		)
		publish(frappe.db.get_value(TASK, name, "assigned_to"))
	return names


def publish(user: str | None) -> None:
	"""Tell the user's open inbox (and the shell's count) that their tasks changed."""
	if user:
		frappe.publish_realtime(REALTIME_EVENT, {"user": user}, user=user, after_commit=True)


def is_snoozed(task) -> bool:
	return bool(task.snoozed_until) and get_datetime(task.snoozed_until) > now_datetime()


def unsnooze() -> None:
	"""Hourly: a task whose snooze has passed comes back to the open list."""
	for task in frappe.get_all(
		TASK,
		{"status": OPEN, "snoozed_until": ("<=", now_datetime())},
		["name", "assigned_to"],
	):
		frappe.db.set_value(TASK, task.name, "snoozed_until", None, update_modified=False)
		publish(task.assigned_to)
