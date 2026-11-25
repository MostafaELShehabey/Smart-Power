"""The lock on field entries (SP-109): late or changed entries are controlled and visible.

An entry can be added or changed until its work date plus the lock days (Field Entry Lock Days,
3 at go-live). After that the day of that vehicle is locked and the only action is to ask to reopen
it with a reason. The projects manager or the admin approves, and a new window of the same length
starts from the approval. The rule field_entry_day_locked sets the level (off, warn or block).

    is_locked(vehicle, work_date)       whether the day is closed today
    ask_to_reopen(vehicle, day, reason) a request and a task with inline approve
    approve(name) / reject(name, why)   the projects manager's or the admin's decision
    lock_entries()                      daily: marks entries Locked and warns of those locking next
    refuse_sync(values)                 an offline entry for a locked day becomes a fix-it task

Entries logged after the normal window, and every approved reopening, are listed in RV2.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, getdate, now_datetime, nowdate

from smart_power.notify import send
from smart_power.rules import BLOCK, OFF, effective_level, get_rule_setting, registry
from smart_power.rules.winch import DAY_LOCKED, RULE_KEY
from smart_power.sp_core.inbox import close_tasks, create_task
from smart_power.sp_core.review_centre import raise_item

ENTRY, REQUEST, TASK = "SP Field Entry", "SP Reopen Request", "SP Task"
OPEN, APPROVED, REJECTED = "Open", "Approved", "Rejected"
LOGGED, LOCKED = "Logged", "Locked"
REOPENERS = ("SP Project Manager", "SP Admin", "System Manager")
SEES_ALL = (*REOPENERS, "SP Winch Manager", "SP Winch Reviewer")
TASK_TYPE, FIX_TASK = "Reopen Request", "Fix Rejected Sync"
LATE = "Late Entry"
REASON_IN_TITLE = 80  # sp-allow-number: keeps the task title within its field
MY_ENTRIES = 20  # sp-allow-number: entries listed on the operator's page, a screen size
EVENT_LOCKING, EVENT_DECIDED, EVENT_ASKED = "entries_locking_24h", "reopen_decided", "reopen_asked"


def lock_days() -> int:
	return cint(frappe.db.get_single_value("Smart Power Settings", "field_entry_lock_days"))


def rule_level() -> str:
	return effective_level(registry()[RULE_KEY], get_rule_setting(RULE_KEY))


def reopened_until(vehicle: str, work_date):
	"""The last day an approved reopening keeps this vehicle's day open."""
	found = frappe.get_all(
		REQUEST,
		filters={"vehicle": vehicle, "work_date": work_date, "status": APPROVED},
		pluck="reopen_until",
		order_by="reopen_until desc",
		limit=1,
	)
	return getdate(found[0]) if found else None


def last_open_day(vehicle: str, work_date):
	normal = getdate(add_days(work_date, lock_days()))
	reopened = reopened_until(vehicle, work_date)
	return max(normal, reopened) if reopened else normal


def is_locked(vehicle: str, work_date) -> bool:
	return lock_days() > 0 and getdate(nowdate()) > last_open_day(vehicle, work_date)


def is_late(work_date) -> bool:
	"""Past the normal window, whether a reopening or a softer rule level let it through."""
	return lock_days() > 0 and getdate(nowdate()) > getdate(add_days(work_date, lock_days()))


def _has_role(roles: tuple, user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(roles) & set(frappe.get_roles(user)))


# --- on the entry ---------------------------------------------------------------------------------


def before_save(doc) -> None:
	doc.reopened = 1 if is_late(doc.work_date) and reopened_until(doc.vehicle, doc.work_date) else 0


def after_insert(doc) -> None:
	"""An entry logged after the normal window is listed for the admin (not an opening debt)."""
	if is_late(doc.work_date) and not doc.get("is_opening"):
		raise_item(
			LATE, doc, _("Logged late: {0} for {1}").format(doc.name, frappe.format(doc.work_date, "Date"))
		)


# --- ask, approve, reject -------------------------------------------------------------------------


@frappe.whitelist()
def lock_state(vehicle: str, work_date: str) -> dict:
	"""What the entry form shows for this vehicle and day."""
	frappe.has_permission(ENTRY, "create", throw=True)
	locked = is_locked(vehicle, work_date) and rule_level() != OFF
	return {
		"locked": locked,
		"blocked": locked and rule_level() == BLOCK,
		"open_until": last_open_day(vehicle, work_date),
		"request": frappe.db.get_value(REQUEST, {"vehicle": vehicle, "work_date": work_date, "status": OPEN}),
	}


@frappe.whitelist(methods=["POST"])
def ask_to_reopen(vehicle: str, work_date: str, reason: str) -> str:
	frappe.has_permission(ENTRY, "create", throw=True)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for reopening the day."), frappe.MandatoryError)
	if not is_locked(vehicle, work_date):
		frappe.throw(_("This day is still open."))
	asked = frappe.db.get_value(REQUEST, {"vehicle": vehicle, "work_date": work_date, "status": OPEN})
	if asked:
		return asked
	doc = frappe.get_doc(
		{
			"doctype": REQUEST,
			"vehicle": vehicle,
			"work_date": work_date,
			"reason": reason,
			"requested_by": frappe.session.user,
			"status": OPEN,
		}
	)
	doc.insert(ignore_permissions=True)  # asked through this service; the DocType has no create right
	create_task(
		TASK_TYPE,
		REQUEST,
		doc.name,
		_reopeners(),
		# the inbox shows the title, and the reason is what the decision rests on
		_("Reopen {0} on {1}: {2}").format(
			vehicle, frappe.format(work_date, "Date"), reason[:REASON_IN_TITLE]
		),
		description=reason,
	)
	# the inbox task waits there; the projects manager and the admin also hear of it (SP-180)
	send(
		EVENT_ASKED,
		_reopeners(),
		REQUEST,
		doc.name,
		_("Asked to reopen {0} on {1}: {2}").format(vehicle, frappe.format(work_date, "Date"), reason),
		from_user=frappe.session.user,
	)
	return doc.name


def _reopeners() -> list[str]:
	from smart_power.sp_sales.quote_request import _users_with

	return sorted({u for role in ("SP Project Manager", "SP Admin") for u in _users_with(role)})


def _open_request(name: str):
	if not _has_role(REOPENERS):
		frappe.throw(_("Only the projects manager or the admin decides a reopening."), frappe.PermissionError)
	doc = frappe.get_doc(REQUEST, name)
	if doc.status != OPEN:
		frappe.throw(_("Request {0} is already {1}.").format(name, _(doc.status)))
	return doc


@frappe.whitelist(methods=["POST"])
def approve(name: str) -> str:
	"""A new window starts now, for every entry of that vehicle on that day."""
	doc = _open_request(name)
	until = add_to_date(now_datetime(), days=lock_days())
	doc.db_set({"status": APPROVED, "approved_by": frappe.session.user, "reopen_until": until})
	for entry in frappe.get_all(
		ENTRY, {"vehicle": doc.vehicle, "work_date": doc.work_date}, ["name", "status"]
	):
		values = {"reopened": 1}
		if entry.status == LOCKED:
			values["status"] = LOGGED
		frappe.db.set_value(ENTRY, entry.name, values)
	close_tasks(REQUEST, doc.name)
	raise_item(
		LATE,
		doc,
		_("Reopened: {0} on {1}: {2}").format(doc.vehicle, frappe.format(doc.work_date, "Date"), doc.reason),
	)
	_tell_requester(doc, _("Reopened until {0}: {1}").format(frappe.format(until, "Date"), doc.vehicle))
	return doc.name


@frappe.whitelist(methods=["POST"])
def reject(name: str, reason: str) -> str:
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for the rejection."), frappe.MandatoryError)
	doc = _open_request(name)
	doc.db_set({"status": REJECTED, "approved_by": frappe.session.user, "reject_reason": reason})
	close_tasks(REQUEST, doc.name)
	_tell_requester(doc, _("Not reopened: {0}: {1}").format(doc.vehicle, reason))
	return doc.name


def _tell_requester(doc, subject: str) -> None:
	if doc.requested_by == frappe.session.user:
		return  # reopened by the one who asked (the field review, SP-110)
	send(EVENT_DECIDED, [doc.requested_by], REQUEST, doc.name, subject, from_user=frappe.session.user)


# --- the daily job --------------------------------------------------------------------------------


def lock_entries() -> list[str]:
	"""Daily: entries past their window show Locked; their operators hear of those locking next."""
	if not lock_days() or rule_level() == OFF:
		return []
	today, locked, locking = getdate(nowdate()), [], {}
	rows = frappe.get_all(
		ENTRY, {"status": LOGGED}, ["name", "vehicle", "work_date", "logged_by", "on_behalf_of"]
	)
	for row in rows:
		last = last_open_day(row.vehicle, row.work_date)
		if today > last:
			frappe.db.set_value(ENTRY, row.name, "status", LOCKED, update_modified=False)
			locked.append(row.name)
		elif today == last:
			locking.setdefault(row.on_behalf_of or row.logged_by, []).append(row.name)
	for user, names in locking.items():
		send(
			EVENT_LOCKING,
			[user],
			ENTRY,
			names[0],
			lambda names=names: _("{0} field entries lock within 24 hours").format(
				len(names)
			),  # per reader (BUG-22)
			from_user="Administrator",
		)
	return locked


def locking_soon(user: str | None = None) -> list[str]:
	"""Entries whose last open day is today: the office sees all, an operator their own."""
	user = user or frappe.session.user
	if not lock_days() or rule_level() == OFF:
		return []
	rows = frappe.get_all(
		ENTRY, {"status": LOGGED}, ["name", "vehicle", "work_date", "logged_by", "on_behalf_of"]
	)
	today = getdate(nowdate())
	everyone = _has_role(SEES_ALL, user)
	return [
		r.name
		for r in rows
		if last_open_day(r.vehicle, r.work_date) == today
		and (everyone or user in (r.logged_by, r.on_behalf_of))
	]


def my_entries(user: str | None = None) -> list[dict]:
	"""The operator's latest entries, with a lock on those whose day has closed."""
	user = user or frappe.session.user
	rows = frappe.get_all(
		ENTRY,
		or_filters={"logged_by": user, "on_behalf_of": user},
		fields=["name", "entry_kind", "vehicle", "work_date", "status"],
		order_by="work_date desc, creation desc",
		limit=MY_ENTRIES,
	)
	return [{**r, "locked": is_locked(r.vehicle, r.work_date)} for r in rows]


# --- an offline entry that arrives too late ---------------------------------------------------------


def refuses_sync(vehicle: str | None, work_date: str | None) -> bool:
	return bool(vehicle and work_date) and rule_level() == BLOCK and is_locked(vehicle, work_date)


def refuse_sync(values: dict) -> dict:
	"""Nothing is saved: the operator gets a fix-it task with the reason, once per vehicle and day."""
	user = values.get("on_behalf_of") or frappe.session.user
	vehicle, work_date = values.get("vehicle"), values.get("work_date")
	subject = _("Day locked: {0} on {1}").format(vehicle, frappe.format(work_date, "Date"))
	filters = {"task_type": FIX_TASK, "assigned_to": user, "subject": subject, "status": OPEN}
	task = frappe.db.get_value(TASK, filters)
	if not task:
		task = (
			frappe.get_doc(
				{
					"doctype": TASK,
					**filters,
					"reference_doctype": "Vehicle",
					"reference_name": vehicle,
					"description": _("This entry reached the server after the day locked. Ask to reopen it."),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return {
		"refused": 1,
		"code": DAY_LOCKED,
		"message": _("Day locked"),
		"vehicle": vehicle,
		"work_date": work_date,
		"task": task,
	}


# --- who sees what --------------------------------------------------------------------------------


def query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _has_role(SEES_ALL, user):
		return ""
	return f"`tabSP Reopen Request`.requested_by = {frappe.db.escape(user)}"
