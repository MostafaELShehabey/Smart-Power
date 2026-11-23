"""sync.push / sync.pull (SP-148): what a phone made offline, and what changed since its last pull.

push: [{doctype, client_uuid, values}] → [{client_uuid, ok, name | error}], one item at a time
(a bad item never stops the others). Each kind goes through its module's own save, which keeps
the same client_uuid to one record:

    SP Field Entry      sp_winch.field_entry.save_entry (a locked day gives its fix-it task)
    SP Custody Expense  sp_finance.custody.add_expense (values carry the custody)
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from smart_power.api.mobile.v1.common import MobileError, endpoint, fail, safe, touch_device

LIST_VALUE = "SP List Value"


def _field_entry(values: dict):
	from smart_power.sp_winch.field_entry import save_entry

	return save_entry(values)


def _custody_expense(values: dict):
	from smart_power.sp_finance.custody import add_expense

	custody = values.pop("custody", None)
	if not custody:
		fail("VALIDATION", _("The expense needs its custody."))
	return add_expense(custody, values)


KINDS = {"SP Field Entry": _field_entry, "SP Custody Expense": _custody_expense}


@endpoint(methods=("POST",))
def push(items: list | str) -> dict:
	items = frappe.parse_json(items) if isinstance(items, str) else items or []
	results = []
	for item in items:
		uuid = item.get("client_uuid")
		save = KINDS.get(item.get("doctype"))
		if not save or not uuid:
			results.append(
				{
					"client_uuid": uuid,
					"ok": False,
					"error": {"code": "VALIDATION", "message_ar": _("Unknown item.")},
				}
			)
			continue
		frappe.db.savepoint("sp_mobile_push")
		try:
			result = save({**(item.get("values") or {}), "client_uuid": uuid})
			ok = not (isinstance(result, dict) and result.get("refused"))
			results.append(
				{
					"client_uuid": uuid,
					"ok": ok,
					"name": result if isinstance(result, str) else None,
					"result": safe(result) if isinstance(result, dict) else None,
				}
			)
		except (MobileError, frappe.ValidationError, frappe.PermissionError) as e:
			frappe.db.rollback(save_point="sp_mobile_push")
			frappe.clear_messages()
			code = getattr(e, "code", None) or (
				"NOT_PERMITTED" if isinstance(e, frappe.PermissionError) else "VALIDATION"
			)
			results.append(
				{
					"client_uuid": uuid,
					"ok": False,
					"error": {"code": code, "message_ar": frappe.utils.strip_html(str(e))},
				}
			)
	touch_device()
	return {"results": results, "server_time": str(now_datetime())}


@endpoint(methods=("GET",))
def pull(since: str | None = None) -> dict:
	"""The lists' values, the user's open tasks and stations, changed since `since` (all when empty)."""
	from smart_power.api.mobile.v1.stations import _station_rows
	from smart_power.sp_core.inbox import open_tasks

	after = get_datetime(since) if since else None
	values = frappe.get_all(
		LIST_VALUE,
		{"modified": (">", after)} if after else {},
		["name", "list_name", "code", "value_ar", "value_en", "is_active", "parent_value", "sort_order"],
		order_by="list_name, sort_order",
	)
	tasks = [t for t in open_tasks() if not after or get_datetime(t.modified) > after]
	touch_device()
	return {
		"server_time": str(now_datetime()),
		"lists": values,
		"tasks": safe([dict(t) for t in tasks]),
		"stations": _station_rows({"modified": (">", after)} if after else {}),
	}
