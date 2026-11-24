"""tasks.list / tasks.action (SP-148): the user's inbox."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe
from smart_power.sp_core import inbox

ACTIONS = ("approve", "reject", "snooze", "wake")


@endpoint(methods=("GET",))
def list(task_type: str | None = None, snoozed: int = 0) -> dict:
	return safe(inbox.my_tasks(task_type, snoozed))


@endpoint(methods=("POST",))
def action(task: str, action: str, payload: dict | str | None = None) -> dict:
	"""approve / reject {reason} / snooze {until} / wake: the inbox's own rules decide."""
	payload = frappe.parse_json(payload) if isinstance(payload, str) else payload or {}
	if action not in ACTIONS:
		fail("VALIDATION", _("Unknown action {0}.").format(action))
	if action in ("approve", "reject"):
		name = inbox.act(task, inbox.APPROVE if action == "approve" else inbox.REJECT, payload.get("reason"))
		return {"ok": True, "record": name}
	if action == "snooze":
		inbox.snooze(task, payload.get("until"))
	else:
		inbox.wake(task)
	return {"ok": True}
