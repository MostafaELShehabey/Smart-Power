"""S4 Reassign, the station part (SP-79; journey J10; ERD 7.2 note 8-11-2026).

The admin hands a station's execution or collection to someone else from a date, with a reason:

    reassign_station(station, kind, to_user, from_date, reason)

A reassignment is one Owner History row (owner, from, to, from date, reason, by). From today it
applies at once; from a later date the row waits as Scheduled and the daily job
(apply_scheduled) applies it on that date. Applying it:
- sets the station's execution_owner or collection_owner (CL1, the row rules and the instalment
  and cheque alerts all follow that field);
- moves the open tasks: a collection hand-over takes the collection calls and the tasks on the
  station's cheques and payments; an execution hand-over takes the station's other tasks;
- for collection, sends the instalments not yet due again to the new owner as they come due,
  so the next "instalment due" alert reaches them;
- tells the old and the new owner, and lists the reassignment for review (RV2).

Payments keep the collection owner of their own date (SP Customer Payment collection_owner), so
those recorded before the hand-over stay with the old owner in reports.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, get_fullname, getdate, now_datetime, today

from smart_power.sp_core.services.audit import audited
from smart_power.sp_stations.station import OWNER_LABELS, is_admin

STATION, TASK, CHEQUE, PAYMENT = "SP Station", "SP Task", "SP Cheque", "SP Customer Payment"
HISTORY, ROW = "SP Owner History", "Payment Schedule"
EXECUTION, COLLECTION = "execution", "collection"
FIELDS = {EXECUTION: "execution_owner", COLLECTION: "collection_owner"}
CLOSED = ("Financially closed", "Cancelled")
TASK_OPEN, CALL_TASK = "Open", "Follow-up Call"  # a collection call (sp_sales.followup)
EVENT = "station_reassigned"
# who may hold each: the collection owner works the CL1 page and reads the station's money; the
# execution owner runs the station (writes it)
OWNER_ROLES = {
	COLLECTION: (
		"SP Admin",
		"SP Accountant",
		"SP Collection Officer",
		"SP Project Manager",
		"SP Customer Followup",
		"SP Followup All",
	),
	EXECUTION: ("SP Admin", "SP Project Manager"),
}


def _label(kind: str) -> str:
	return OWNER_LABELS[FIELDS[kind]]


def can_hold(user: str, kind: str) -> bool:
	return bool(set(OWNER_ROLES[kind]) & set(frappe.get_roles(user)))


@frappe.whitelist()
def eligible_users(kind: str) -> list[dict]:
	"""For the Reassign dialog: the enabled users who may hold this owner."""
	_check_kind(kind)
	users = frappe.get_all(
		"Has Role",
		{"role": ("in", OWNER_ROLES[kind]), "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	enabled = frappe.get_all(
		"User",
		{"name": ("in", users or [""]), "enabled": 1, "user_type": "System User"},
		["name", "full_name"],
		order_by="full_name asc",
	)
	return [{"value": u.name, "label": u.full_name or u.name} for u in enabled if u.name != "Administrator"]


def _check_kind(kind: str) -> None:
	if kind not in FIELDS:
		frappe.throw(_("Unknown owner {0}.").format(frappe.bold(kind)))


@frappe.whitelist(methods=["POST"])
@audited("Reassigned", "SP Station")  # X13 (SP-137)
def reassign_station(
	station: str, kind: str, to_user: str, from_date: str | None = None, reason: str | None = None
) -> dict:
	"""Give the station's execution or collection to to_user from from_date (today when empty).
	Returns {applied, from_date}."""
	if not is_admin():
		frappe.throw(_("Only the admin reassigns a station."), frappe.PermissionError)
	_check_kind(kind)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is needed to reassign."), frappe.MandatoryError)
	day = getdate(from_date or today())
	if day < getdate(today()):
		frappe.throw(_("The reassignment starts today or later, not on a past date."))
	doc = frappe.get_doc(STATION, station)
	if doc.status in CLOSED:
		frappe.throw(_("Station {0} is {1}; it is not reassigned.").format(doc.name, _(doc.status)))
	if not to_user or not frappe.db.get_value("User", to_user, "enabled"):
		frappe.throw(_("Choose an active user to reassign to."), frappe.MandatoryError)
	if not can_hold(to_user, kind):
		frappe.throw(
			_("{0} cannot be the {1}: they need one of the roles {2}.").format(
				frappe.bold(get_fullname(to_user)),
				_(_label(kind)),
				", ".join(_(r) for r in OWNER_ROLES[kind]),
			)
		)
	_drop_scheduled(doc, kind)
	if day <= getdate(today()):
		if doc.get(FIELDS[kind]) == to_user:
			frappe.throw(_("{0} is already the {1}.").format(get_fullname(to_user), _(_label(kind))))
		apply(doc, kind, to_user, reason, frappe.session.user)
		applied = True
	else:
		doc.append(
			"owner_history",
			{
				"role_kind": _label(kind),
				"from_user": doc.get(FIELDS[kind]),
				"to_user": to_user,
				"from_date": get_datetime(day),
				"reason": reason,
				"changed_by": frappe.session.user,
				"is_pending": 1,
			},
		)
		doc.flags.ignore_permissions = True
		doc.save()
		applied = False
	_review(doc, kind, to_user, day, reason)
	return {"applied": applied, "from_date": str(day)}


def _drop_scheduled(doc, kind: str) -> None:
	"""A new reassignment replaces one still waiting for the same owner."""
	for row in list(doc.owner_history):
		if row.is_pending and row.role_kind == _label(kind):
			doc.remove(row)


def apply(doc, kind: str, to_user: str, reason: str, by: str, row=None) -> None:
	"""Make to_user the owner now: the field, the history, the tasks, the alerts, both told."""
	fieldname = FIELDS[kind]
	old = doc.get(fieldname)
	doc.set(fieldname, to_user)
	if row:  # the scheduled row becomes the history row
		row.is_pending = 0
		row.from_user = old
		doc.flags.sp_owner_row_done = True
	doc.flags.sp_owner_change_reason = reason
	doc.flags.ignore_permissions = True
	doc.save()
	_move_tasks(doc, kind, old, to_user)
	if kind == COLLECTION:
		_alert_again(doc)
	_tell(doc, kind, old, to_user, reason, by)


def _move_tasks(doc, kind: str, old: str | None, new: str) -> None:
	if not old:
		return
	open_tasks = {"assigned_to": old, "status": TASK_OPEN}
	on_station = frappe.get_all(
		TASK,
		{**open_tasks, "reference_doctype": STATION, "reference_name": doc.name},
		["name", "task_type"],
	)
	if kind == COLLECTION:
		names = [t.name for t in on_station if t.task_type == CALL_TASK]
		for doctype, field in ((CHEQUE, "station"), (PAYMENT, "station")):
			linked = frappe.get_all(doctype, {field: doc.name}, pluck="name")
			if linked:
				names += frappe.get_all(
					TASK,
					{**open_tasks, "reference_doctype": doctype, "reference_name": ("in", linked)},
					pluck="name",
				)
	else:
		names = [t.name for t in on_station if t.task_type != CALL_TASK]
	for name in names:
		frappe.db.set_value(TASK, name, "assigned_to", new)


def _alert_again(doc) -> None:
	"""The instalments not yet paid nor overdue alert again, now to the new collection owner."""
	if not doc.sales_order:
		return
	for row in frappe.get_all(
		ROW, {"parent": doc.sales_order, "parenttype": "Sales Order"}, ["name", "sp_status"]
	):
		if row.sp_status not in ("Paid", "Overdue"):
			frappe.db.set_value(ROW, row.name, "sp_due_alerted", 0, update_modified=False)


def _tell(doc, kind: str, old: str | None, new: str, reason: str, by: str) -> None:
	from smart_power.notify import send

	customer = doc.customer_name or doc.customer
	what = _(_label(kind))
	send(
		EVENT,
		[new],
		STATION,
		doc.name,
		_("You are now the {0} of station {1} ({2}): {3}").format(what, doc.name, customer, reason),
		from_user=by,
	)
	if old and old != new:
		send(
			EVENT,
			[old],
			STATION,
			doc.name,
			_("Station {0} ({1}) moved to {2} as {3}: {4}").format(
				doc.name, customer, get_fullname(new), what, reason
			),
			from_user=by,
		)


def _review(doc, kind: str, to_user: str, day, reason: str) -> None:
	from smart_power.sp_core.review_centre import raise_item

	raise_item(
		"Reassignment",
		doc,
		_("{0} of station {1} to {2} from {3}: {4}").format(
			_(_label(kind)), doc.name, get_fullname(to_user), frappe.format(day, "Date"), reason
		),
	)


# --- the daily job -------------------------------------------------------------------------------


def apply_scheduled() -> list[str]:
	"""Daily, before the instalment alerts: the reassignments whose date has come apply."""
	now = now_datetime()
	rows = frappe.get_all(
		HISTORY,
		{"parenttype": STATION, "is_pending": 1, "from_date": ("<=", now)},
		["name", "parent"],
		order_by="from_date asc",
	)
	done = []
	for parent in dict.fromkeys(r.parent for r in rows):
		doc = frappe.get_doc(STATION, parent)
		for row in [r for r in doc.owner_history if r.is_pending and get_datetime(r.from_date) <= now]:
			kind = next(k for k in FIELDS if _label(k) == row.role_kind)
			if doc.status in CLOSED:
				doc.remove(row)
				doc.flags.ignore_permissions = True
				doc.save()
				continue
			apply(doc, kind, row.to_user, row.reason, row.changed_by, row=row)
			done.append(f"{doc.name}:{kind}")
	return done


def scheduled(doc) -> list[dict]:
	"""For the station form: the reassignments still waiting."""
	return [
		{
			"owner": _(r.role_kind),
			"to_user": get_fullname(r.to_user),
			"from_date": frappe.format(getdate(r.from_date), "Date"),
		}
		for r in doc.owner_history
		if r.is_pending
	]


# --- payments keep the owner of their date -----------------------------------------------------


def owner_on(station: str, day=None) -> str | None:
	"""The station's collection owner on day: the last applied hand-over by then."""
	day = getdate(day or today())
	rows = frappe.get_all(
		HISTORY,
		{"parenttype": STATION, "parent": station, "role_kind": _label(COLLECTION), "is_pending": 0},
		["to_user", "from_date"],
		order_by="from_date asc, idx asc",
	)
	owner = None
	for row in rows:
		if row.from_date and getdate(row.from_date) <= day:
			owner = row.to_user
	return owner or frappe.db.get_value(STATION, station, "collection_owner")
