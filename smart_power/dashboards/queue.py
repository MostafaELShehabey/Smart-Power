"""My queue (SP-38, G2): what waits for me today, the inbox's open tasks and my open to-dos
(ERPNext assignments), soonest due first."""

import frappe
from frappe.utils import get_datetime

QUEUE_LIMIT = 20  # sp-allow-number: how many rows the home page lists (the inbox has them all)


@frappe.whitelist()
def get_my_queue() -> list[dict]:
	from smart_power.sp_core.inbox import open_tasks

	user = frappe.session.user
	rows = [
		{
			"title": t.subject,
			"kind": t.task_type,
			"due": t.due_at,
			"high": t.priority == "High",
			"doctype": t.reference_doctype,
			"name": t.reference_name,
		}
		for t in open_tasks(user)
	]
	for todo in frappe.get_all(
		"ToDo",
		filters={"allocated_to": user, "status": "Open"},
		fields=["description", "date", "reference_type", "reference_name", "priority"],
	):
		rows.append(
			{
				"title": frappe.utils.strip_html(todo.description or "")[:140],  # sp-allow-number: one line
				"kind": "ToDo",
				"due": todo.date,
				"high": todo.priority == "High",
				"doctype": todo.reference_type,
				"name": todo.reference_name,
			}
		)
	far = get_datetime("9999-12-31")
	rows.sort(key=lambda r: (not r["high"], get_datetime(r["due"]) if r["due"] else far))
	return rows[:QUEUE_LIMIT]
