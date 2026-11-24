"""calls.today (SP-148): the follow-up calls due today or late."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe


@endpoint(methods=("GET",))
def today() -> list[dict]:
	return frappe.get_all(
		"SP Task",
		{
			"assigned_to": frappe.session.user,
			"status": "Open",
			"task_type": "Follow-up Call",
			"due_at": ("<=", f"{frappe.utils.today()} 23:59:59"),
		},
		["name", "subject", "reference_doctype", "reference_name", "due_at"],
		order_by="due_at asc",
	)
