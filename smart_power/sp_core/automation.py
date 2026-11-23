"""X9 Automations (SP-135): when → only when → then, set up by the admin in SP Automation.

    on_doc_event(doc)       "*" after_insert / on_update: the record-event automations of its type
    run_daily()             the time-based ones: N days before or after a date field
    plan(auto, doc)         what an automation would do on a record (nothing done)
    test(name, docname)     the same for the form's "Test" button: the conditions and the plan

A field, in a condition or as a recipient, may follow links with dots: on an instalment (a row of
the contract's Payment Schedule), `parent.sp_station.collection_owner` is the station's collection
owner. A record-event automation acts each time its event happens. A time-based one acts once per
record (SP Automation Log), and only for records whose day (the date ± N days) falls on or after
the day the automation was made, so an old backlog never floods anyone (owner's decision
24-11-2026); a missed day is caught up. A paused automation does nothing. An automation that fails
is logged and never blocks the user's save.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import add_days, cstr, flt, getdate, now_datetime, today

AUTOMATION, LOG = "SP Automation", "SP Automation Log"
ON_CREATE, ON_STATUS, ON_CHANGE = "On create", "On status change", "On field change"
DAYS_BEFORE, DAYS_AFTER = "Days before a date", "Days after a date"
EVENT_TRIGGERS, TIME_TRIGGERS = (ON_CREATE, ON_STATUS, ON_CHANGE), (DAYS_BEFORE, DAYS_AFTER)
NOTIFY, TASK, ASSIGN = "Notify", "Create Task", "Assign"
ROLE, USER, FIELD = "Role", "User", "Field"
EVENT = "automation"
PLACEHOLDER = re.compile(r"\{\{\s*doc\.([A-Za-z0-9_.]+)\s*\}\}")
CACHE_KEY = "sp_automation_map"
DATE_TYPES = ("Date", "Datetime")
ADMIN_ROLES = ("SP Admin", "System Manager")
SKIPPED = (AUTOMATION, LOG, "Notification Log", "ToDo", "SP Task", "Version", "Comment", "Error Log")


# --- reading a record ------------------------------------------------------------------------------


def resolve(doc, path: str):
	"""A field's value, following links (and `parent` from a table row) with dots."""
	current = doc
	parts = [p for p in (path or "").split(".") if p]
	for i, part in enumerate(parts):
		if current is None:
			return None
		if part == "parent":
			current = (
				frappe.get_doc(current.parenttype, current.parent)
				if current.get("parenttype") and current.get("parent")
				else None
			)
			continue
		if i == len(parts) - 1:
			return current.get(part)
		df = frappe.get_meta(current.doctype).get_field(part)
		value = current.get(part)
		if not (df and value and df.fieldtype in ("Link", "Dynamic Link")):
			return None
		target = df.options if df.fieldtype == "Link" else current.get(df.options)
		current = frappe.get_doc(target, value) if target and frappe.db.exists(target, value) else None
	return current.name if hasattr(current, "name") else current


def _number(value):
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def check(cond, doc) -> bool:
	actual, wanted, op = resolve(doc, cond.field), cstr(cond.value).strip(), cond.op
	if op == "is set":
		return actual not in (None, "", 0)
	if op == "is not set":
		return actual in (None, "", 0)
	if op in ("in", "not in"):
		found = cstr(actual) in [v.strip() for v in wanted.split(",")]
		return found if op == "in" else not found
	if op == "contains":
		return wanted in cstr(actual)
	a, b = _number(actual), _number(wanted)
	if a is None or b is None:
		a, b = cstr(actual), wanted
	return {
		"=": a == b,
		"!=": a != b,
		">": a > b,
		"<": a < b,
		">=": a >= b,
		"<=": a <= b,
	}.get(op, False)


def matches(auto, doc) -> bool:
	return all(check(c, doc) for c in auto.conditions)


# --- what it does -----------------------------------------------------------------------------------


def _reference(doc) -> tuple[str, str]:
	"""Where the alert and the task point: a table row's own record (its contract, for an
	instalment), since a row cannot be opened."""
	if doc.meta.istable and doc.get("parenttype"):
		return doc.parenttype, doc.parent
	return doc.doctype, doc.name


def recipients(action, doc) -> list[str]:
	who = (action.recipient or "").strip()
	if action.recipient_type == ROLE:
		users = frappe.get_all("Has Role", {"role": who, "parenttype": "User"}, pluck="parent", distinct=True)
		users = frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")
	elif action.recipient_type == USER:
		users = [who]
	else:
		value = resolve(doc, who)
		users = [value] if isinstance(value, str) else []
	return sorted({u for u in users if u and u not in ("Guest",) and frappe.db.exists("User", u)})


def _subject(auto, action, doc) -> str:
	if (action.message or "").strip():
		# {{ doc.field }} placeholders only (a path through links works too), never a template the
		# server would run: the admin's message is text
		return PLACEHOLDER.sub(lambda m: cstr(resolve(doc, m.group(1))), action.message)
	return _("{0}: {1} {2}").format(auto.title, _(doc.doctype), doc.name)


def plan(auto, doc) -> list[dict]:
	out = []
	ref_doctype, ref_name = _reference(doc)
	for action in auto.actions:
		row = {
			"kind": action.kind,
			"users": recipients(action, doc),
			"subject": _subject(auto, action, doc),
			"reference_doctype": ref_doctype,
			"reference_name": ref_name,
		}
		if action.kind == TASK:
			row["task_type"] = action.task_type or "Other"
			row["due_days"] = action.due_days or 0
			row["due"] = str(add_days(today(), row["due_days"]))
		out.append(row)
	return out


def execute(auto, doc) -> list[dict]:
	from smart_power.notify import send
	from smart_power.sp_core.inbox import create_task

	done = plan(auto, doc)
	for row in done:
		if not row["users"]:
			continue
		if row["kind"] == NOTIFY:
			send(EVENT, row["users"], row["reference_doctype"], row["reference_name"], row["subject"])
		elif row["kind"] == TASK:
			due = add_days(now_datetime(), row["due_days"])
			create_task(
				row["task_type"],
				row["reference_doctype"],
				row["reference_name"],
				row["users"],
				row["subject"],
				due_at=due,
			)
		elif row["kind"] == ASSIGN:
			for user in row["users"]:
				frappe.get_doc(
					{
						"doctype": "ToDo",
						"allocated_to": user,
						"reference_type": row["reference_doctype"],
						"reference_name": row["reference_name"],
						"description": row["subject"],
						"assigned_by": frappe.session.user,
					}
				).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": LOG,
			"automation": auto.name,
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"fired_on": now_datetime(),
			"actions": json.dumps(done, ensure_ascii=False, default=str),
		}
	).insert(ignore_permissions=True)
	return done


def _run(auto, doc) -> None:
	"""Act if the conditions hold. A broken automation is logged and never blocks the save."""
	try:
		frappe.db.savepoint("sp_automation")
		if matches(auto, doc):
			execute(auto, doc)
	except Exception:
		frappe.db.rollback(save_point="sp_automation")
		frappe.log_error(title=_("Automation {0} failed").format(auto.name))


# --- record events ----------------------------------------------------------------------------------


def clear_cache() -> None:
	frappe.cache.delete_value(CACHE_KEY)


def _map() -> dict:
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is None:
		cached = {}
		if frappe.db.table_exists(AUTOMATION):
			for row in frappe.get_all(
				AUTOMATION, {"is_active": 1, "trigger": ("in", EVENT_TRIGGERS)}, ["name", "doctype_name"]
			):
				cached.setdefault(row.doctype_name, []).append(row.name)
		frappe.cache.set_value(CACHE_KEY, cached)
	return cached


def on_doc_event(doc, method=None) -> None:
	if doc.doctype in SKIPPED or frappe.flags.in_install or frappe.flags.in_migrate:
		return
	names = _map().get(doc.doctype)
	if not names:
		return
	for name in names:
		auto = frappe.get_cached_doc(AUTOMATION, name)
		if method == "after_insert":
			fire = auto.trigger == ON_CREATE
		elif doc.flags.in_insert:
			fire = False  # on_update also runs on insert: the record did not change, it was made
		else:
			field = auto.watch_field or ("status" if auto.trigger == ON_STATUS else None)
			fire = auto.trigger in (ON_STATUS, ON_CHANGE) and bool(field) and doc.has_value_changed(field)
		if fire:
			_run(auto, doc)


# --- time-based -------------------------------------------------------------------------------------


def due_names(auto, on=None) -> list[str]:
	"""The records whose day (date ± N) has come, since the day the automation was made."""
	day, made, n = getdate(on or today()), getdate(auto.creation), auto.offset_days or 0
	shift = -n if auto.trigger == DAYS_AFTER else n  # the date a record must have today
	field = auto.date_field
	return frappe.get_all(
		auto.doctype_name,
		{field: ("between", (add_days(made, shift), add_days(day, shift)))},
		pluck="name",
	)


def run_daily(on=None) -> int:
	"""Daily: each time-based automation acts once per record whose day has come."""
	fired = 0
	for name in frappe.get_all(AUTOMATION, {"is_active": 1, "trigger": ("in", TIME_TRIGGERS)}, pluck="name"):
		auto = frappe.get_doc(AUTOMATION, name)
		done = set(frappe.get_all(LOG, {"automation": name}, pluck="reference_name"))
		for docname in due_names(auto, on):
			if docname in done:
				continue
			doc = frappe.get_doc(auto.doctype_name, docname)
			before = frappe.db.count(LOG, {"automation": name})
			_run(auto, doc)
			fired += frappe.db.count(LOG, {"automation": name}) - before
	return fired


# --- the form ---------------------------------------------------------------------------------------


def _field_exists(doctype: str, path: str) -> bool:
	first = (path or "").split(".")[0]
	return first == "parent" or frappe.get_meta(doctype).has_field(first) or first in ("name", "owner")


def validate_automation(doc) -> None:
	if not frappe.db.exists("DocType", doc.doctype_name):
		frappe.throw(_("Pick the record the automation watches."))
	if doc.trigger in TIME_TRIGGERS:
		df = frappe.get_meta(doc.doctype_name).get_field(doc.date_field or "")
		if not df or df.fieldtype not in DATE_TYPES:
			frappe.throw(
				_("{0} is not a date field of {1}.").format(doc.date_field or "", _(doc.doctype_name))
			)
		if (doc.offset_days or 0) < 0:
			frappe.throw(_("The days cannot be negative."))
	if doc.trigger == ON_CHANGE and not doc.watch_field:
		frappe.throw(_("Pick the field whose change starts the automation."))
	for row in doc.conditions:
		if not _field_exists(doc.doctype_name, row.field):
			frappe.throw(
				_("Condition {0}: {1} is not a field of {2}.").format(row.idx, row.field, _(doc.doctype_name))
			)
	if not doc.actions:
		frappe.throw(_("Add at least one action."))
	for row in doc.actions:
		who = (row.recipient or "").strip()
		if row.recipient_type == ROLE and not frappe.db.exists("Role", who):
			frappe.throw(_("Action {0}: {1} is not a role.").format(row.idx, who))
		if row.recipient_type == USER and not frappe.db.exists("User", who):
			frappe.throw(_("Action {0}: {1} is not a user.").format(row.idx, who))
		if row.recipient_type == FIELD and not _field_exists(doc.doctype_name, who):
			frappe.throw(
				_("Action {0}: {1} is not a field of {2}.").format(row.idx, who, _(doc.doctype_name))
			)


@frappe.whitelist()
def test(name: str, docname: str) -> dict:
	"""A dry run on one record: each condition with its value, and what would be done."""
	frappe.only_for(ADMIN_ROLES)
	auto = frappe.get_doc(AUTOMATION, name)
	doc = frappe.get_doc(auto.doctype_name, docname)
	conditions = [
		{
			"field": c.field,
			"op": c.op,
			"value": c.value,
			"actual": cstr(resolve(doc, c.field)),
			"ok": check(c, doc),
		}
		for c in auto.conditions
	]
	ok = all(c["ok"] for c in conditions)
	return {
		"matches": ok,
		"conditions": conditions,
		"actions": plan(auto, doc) if ok else [],
		"active": auto.is_active,
	}
