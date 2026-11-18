"""The task inbox service (SP-39, G3): one inbox instead of WhatsApp groups.

    create_task(task_type, reference_doctype, reference_name, users, subject, ...)
    close_tasks(reference_doctype, reference_name, task_type=None)

Each module makes its tasks through these when something needs a person (a payment to confirm,
a settlement to approve, a password to reset ...) and closes them when it is done. A task can be
snoozed until a date and time; the hourly job brings it back. Every change reaches the assignee's
open inbox at once (realtime "sp_tasks").

The inbox page (sp-task-inbox) lists my open tasks by type; payment, transfer and settlement tasks
are approved or rejected right there through TASK_HANDLERS, which re-check the right and the state.
"""

import frappe
from frappe import _
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


# --- the inbox page (G3): my open tasks, inline approve / reject, snooze -------------------------

# Task types that can be approved or rejected right from the inbox: (approve, reject(name, reason)).
# Each handler checks the user's right and the record's state again.
TASK_HANDLERS = {
	"Payment to Confirm": (
		"smart_power.sp_finance.customer_payment.confirm",
		"smart_power.sp_finance.customer_payment.reject",
	),
	"Supplier Payment to Confirm": (
		"smart_power.sp_finance.supplier_payment.confirm",
		"smart_power.sp_finance.supplier_payment.reject",
	),
	"Transfer to Confirm": (
		"smart_power.sp_finance.transfer.confirm",
		"smart_power.sp_finance.transfer.reject",
	),
	"Settlement to Approve": (
		"smart_power.sp_finance.custody.confirm",
		"smart_power.sp_finance.custody.reject",
	),
}
APPROVE, REJECT = "approve", "reject"
FIELDS = (
	"name",
	"subject",
	"task_type",
	"priority",
	"amount",
	"image",
	"description",
	"due_at",
	"creation",
	"snoozed_until",
	"reference_doctype",
	"reference_name",
)


def _sees_all(user: str) -> bool:
	return user == "Administrator" or bool({"SP Admin", "System Manager"} & set(frappe.get_roles(user)))


def open_tasks(user: str | None = None, snoozed: bool = False) -> list:
	"""The user's open tasks: the ones waiting now, or the snoozed ones; high priority, then oldest."""
	user = user or frappe.session.user
	now = now_datetime()
	filters = {"assigned_to": user, "status": OPEN}
	if snoozed:
		filters["snoozed_until"] = (">", now)
	rows = frappe.get_all(TASK, filters=filters, fields=list(FIELDS), order_by="creation asc")
	rows.sort(key=lambda r: r.priority != HIGH)  # high first; the oldest first within each
	if not snoozed:
		rows = [r for r in rows if not is_snoozed(r)]
	return rows


def open_count(user: str | None = None) -> int:
	"""How many tasks wait for the user now (the shell's count)."""
	return len(open_tasks(user))


@frappe.whitelist()
def my_tasks(task_type: str | None = None, snoozed: int = 0) -> dict:
	"""The inbox: my open tasks (or my snoozed ones), with the count per type and their actions."""
	rows = open_tasks(snoozed=bool(int(snoozed)))
	counts = {}
	for row in rows:
		counts[row.task_type] = counts.get(row.task_type, 0) + 1
	if task_type:
		rows = [r for r in rows if r.task_type == task_type]
	for row in rows:
		row.inline = row.task_type in TASK_HANDLERS
	return {"tasks": rows, "counts": counts, "snoozed": len(open_tasks(snoozed=True))}


def _my_open_task(name: str):
	task = frappe.get_doc(TASK, name)
	user = frappe.session.user
	if task.assigned_to != user and not _sees_all(user):
		frappe.throw(_("This task is not yours."), frappe.PermissionError)
	if task.status != OPEN:
		frappe.throw(_("This task is already {0}.").format(_(task.status)))
	return task


@frappe.whitelist(methods=["POST"])
def act(task: str, action: str, reason: str | None = None) -> str:
	"""Approve or reject the task's record right from the inbox; the record's own rule decides."""
	doc = _my_open_task(task)
	handlers = TASK_HANDLERS.get(doc.task_type)
	if not handlers or action not in (APPROVE, REJECT):
		frappe.throw(_("{0} is not done from the inbox; open the record.").format(_(doc.task_type)))
	if action == REJECT and not (reason or "").strip():
		frappe.throw(_("Give the reason for rejecting."))
	approve, reject = (frappe.get_attr(path) for path in handlers)
	if action == APPROVE:
		approve(doc.reference_name)
	else:
		reject(doc.reference_name, reason)
	close_tasks(doc.reference_doctype, doc.reference_name, doc.task_type)
	return doc.reference_name


@frappe.whitelist(methods=["POST"])
def snooze(task: str, until: str) -> None:
	"""Hide the task until a date and time; it comes back by itself."""
	doc = _my_open_task(task)
	if get_datetime(until) <= now_datetime():
		frappe.throw(_("Snooze until a time that is still to come."))
	doc.db_set("snoozed_until", get_datetime(until))
	publish(doc.assigned_to)


@frappe.whitelist(methods=["POST"])
def wake(task: str) -> None:
	"""Bring a snoozed task back now."""
	doc = _my_open_task(task)
	doc.db_set("snoozed_until", None)
	publish(doc.assigned_to)
