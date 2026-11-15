"""Following a case up after its quote is sent (SP-67, F2 / F3).

A logged call (SP Call Log):
- closes the case's open call task, and a next call date becomes a new call task for the
  follow-up owner (the first one comes from sending the quote, SP-61);
- moves a "Sent to customer" case to "Follow-up" and marks the case touched;
- "Wants revision" tells the quote creator, with the note;
- "Lost" is followed by the lost dialog on the form (mark_lost), with the case's lost reason.

case_view(case) gives the F2 screen its call timeline and the quote at sale prices only.
"""

import frappe
from frappe import _
from frappe.utils import get_fullname, now_datetime

from smart_power.sp_sales.case import touch

CASE, TASK, CALL, STATION = "SP Case", "SP Task", "SP Call Log", "SP Station"
CALL_TASK, TASK_OPEN, TASK_DONE, TASK_CANCELLED = "Follow-up Call", "Open", "Done", "Cancelled"
RESULTS = "Call Result"
WANTS_REVISION, LOST = "WANTS_REVISION", "LOST"
SENT, FOLLOW_UP, CLOSED = "Sent to customer", "Follow-up", ("Won", "Lost")


def _code(result: str | None) -> str | None:
	return frappe.db.get_value("SP List Value", result, "code") if result else None


def validate_call(doc) -> None:
	if frappe.db.get_value("SP List Value", doc.result, "list_name") != RESULTS:
		frappe.throw(_("{0} is not a call result.").format(frappe.bold(doc.result)))
	if doc.get("station"):
		# a collection call on a station (SP-81): its case is won already
		station = frappe.db.get_value(STATION, doc.station, ["case", "customer_name"], as_dict=True)
		if station:
			doc.case = doc.case or station.case
			doc.customer_name = doc.customer_name or station.customer_name
	elif frappe.db.get_value(CASE, doc.case, "status") in CLOSED and doc.is_new():
		frappe.throw(_("Case {0} is closed; reopen it before logging calls.").format(doc.case))
	if doc.next_call_at and frappe.utils.get_datetime(doc.next_call_at) < frappe.utils.get_datetime(
		doc.call_time
	):
		frappe.throw(_("The next call cannot be before this call."))
	doc.logged_by = doc.logged_by or frappe.session.user


def after_call(doc) -> None:
	if doc.get("station"):
		_after_station_call(doc)
		return
	case = frappe.get_doc(CASE, doc.case)
	_close_call_tasks(case.name)
	if doc.next_call_at and case.follow_up_owner:
		frappe.get_doc(
			{
				"doctype": TASK,
				"subject": _("Call {0}").format(case.customer_name or case.customer),
				"task_type": CALL_TASK,
				"assigned_to": case.follow_up_owner,
				"due_at": doc.next_call_at,
				"reference_doctype": CASE,
				"reference_name": case.name,
				"description": doc.note,
			}
		).insert(ignore_permissions=True)
	if case.status == SENT:
		from frappe.model.workflow import apply_workflow

		apply_workflow(case, "Start Follow-up")
	touch(case.name)
	from smart_power.sp_sales.board import publish_update

	publish_update(case)  # the card's last call changes on the board (SP-66)
	if _code(doc.result) == WANTS_REVISION and case.quote_creator:
		_notify(
			case,
			case.quote_creator,
			_("{0} wants the quote revised: {1}").format(case.customer_name or case.customer, doc.note or ""),
		)


def _after_station_call(doc) -> None:
	"""A collection call: the station's open call task closes; a next call date makes a new one
	for the collection owner."""
	for name in frappe.get_all(
		TASK,
		{
			"reference_doctype": STATION,
			"reference_name": doc.station,
			"task_type": CALL_TASK,
			"status": TASK_OPEN,
		},
		pluck="name",
	):
		frappe.db.set_value(
			TASK,
			name,
			{"status": TASK_DONE, "completed_by": frappe.session.user, "completed_on": now_datetime()},
		)
	owner = frappe.db.get_value(STATION, doc.station, "collection_owner")
	if doc.next_call_at and owner:
		frappe.get_doc(
			{
				"doctype": TASK,
				"subject": _("Collection call: {0}").format(doc.customer_name or doc.station),
				"task_type": CALL_TASK,
				"assigned_to": owner,
				"due_at": doc.next_call_at,
				"reference_doctype": STATION,
				"reference_name": doc.station,
				"description": doc.note,
			}
		).insert(ignore_permissions=True)


def _close_call_tasks(case: str) -> None:
	for name in frappe.get_all(
		TASK,
		{"reference_doctype": CASE, "reference_name": case, "task_type": CALL_TASK, "status": TASK_OPEN},
		pluck="name",
	):
		frappe.db.set_value(
			TASK,
			name,
			{"status": TASK_DONE, "completed_by": frappe.session.user, "completed_on": now_datetime()},
		)


def _notify(case, user: str, subject: str) -> None:
	from frappe.desk.doctype.notification_log.notification_log import make_notification_logs

	make_notification_logs(
		frappe._dict(
			{
				"type": "Alert",
				"document_type": CASE,
				"document_name": case.name,
				"subject": subject,
				"from_user": frappe.session.user,
			}
		),
		[user],
	)


@frappe.whitelist(methods=["POST"])
def log_call(case: str, result: str, note: str | None = None, next_call_at: str | None = None) -> dict:
	"""F3: log a call on a case (the follow-up owner, the admin or the follow-up lead).
	`lost` tells the form to open the lost dialog."""
	frappe.get_doc(CASE, case).check_permission("write")
	call = frappe.get_doc(
		{"doctype": CALL, "case": case, "result": result, "note": note, "next_call_at": next_call_at}
	).insert()
	return {"name": call.name, "lost": _code(result) == LOST}


@frappe.whitelist(methods=["POST"])
def mark_lost(case: str, lost_reason: str, lost_note: str | None = None) -> str:
	"""The lost dialog after a "Lost" call: the reason, then the case's Mark Lost."""
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc(CASE, case)
	doc.check_permission("write")
	if not lost_reason:
		frappe.throw(_("A lost case needs a lost reason."), frappe.MandatoryError)
	# the workflow reloads the case, so the reason is saved first
	doc.db_set({"lost_reason": lost_reason, "lost_note": lost_note})
	_close_call_tasks(case)
	# nothing else is left to do on a lost case
	for name in frappe.get_all(
		TASK, {"reference_doctype": CASE, "reference_name": case, "status": TASK_OPEN}, pluck="name"
	):
		frappe.db.set_value(TASK, name, "status", TASK_CANCELLED)
	return apply_workflow(frappe.get_doc(CASE, case), "Mark Lost").name


@frappe.whitelist()
def case_view(case: str) -> dict:
	"""F2: the call timeline and the case's quote at sale prices only (no cost, ever)."""
	from smart_power.sp_quotes.quote_print import print_lines

	doc = frappe.get_doc(CASE, case)
	doc.check_permission("read")
	calls = frappe.get_all(
		CALL,
		filters={"case": case},
		fields=["name", "call_time", "result", "note", "next_call_at", "logged_by"],
		order_by="call_time desc",
	)
	labels = dict(
		frappe.get_all(
			"SP List Value",
			filters={"name": ("in", [c.result for c in calls] or [""])},
			fields=["name", "value_ar"],
			as_list=True,
		)
	)
	for call in calls:
		call.result_label = labels.get(call.result) or call.result
		call.logged_by_name = get_fullname(call.logged_by)
	quote_name = doc.accepted_quotation or frappe.db.get_value(
		"Quotation", {"sp_case": case, "docstatus": 1}, "name", order_by="sp_version desc"
	)
	quote = None
	if quote_name:
		q = frappe.get_doc("Quotation", quote_name)
		quote = {
			"name": q.name,
			"option": q.sp_option_label,
			"version": q.sp_version,
			"status": q.sp_status,
			"valid_till": q.valid_till,
			"currency": q.currency,
			"total": q.rounded_total or q.grand_total,
			"lines": print_lines(q.items),
			"schedule": [
				{"due_date": r.due_date, "amount": r.payment_amount, "description": r.description}
				for r in q.get("payment_schedule") or []
			],
		}
	return {"calls": calls, "quote": quote, "status": doc.status}


# --- F5 hand over and S4 reassign (SP-69) ------------------------------------------------------

FOLLOWUP_ROLE = "SP Customer Followup"
OWNER_FIELD = "follow_up_owner"


def can_hand_over(case, user: str | None = None) -> bool:
	"""F5 is for the case's own follow-up owner, who holds the follow-up role (not marketing)."""
	user = user or frappe.session.user
	return (
		case.get(OWNER_FIELD) == user
		and FOLLOWUP_ROLE in frappe.get_roles(user)
		and case.get("status") not in CLOSED
	)


@frappe.whitelist(methods=["POST"])
def hand_over(case: str, to_user: str, note: str | None = None) -> str:
	"""F5: give my case to a colleague at once, with no approval. The history keeps the date,
	from and to; the open call tasks and the board card move with the case."""
	doc = frappe.get_doc(CASE, case)
	if not can_hand_over(doc):
		frappe.throw(
			_("Only the case's follow-up owner can hand it over. Ask the admin to reassign it."),
			frappe.PermissionError,
		)
	if to_user == frappe.session.user:
		frappe.throw(_("The case is already yours."))
	if not frappe.db.get_value("User", to_user, "enabled") or FOLLOWUP_ROLE not in frappe.get_roles(to_user):
		frappe.throw(
			_("{0} does not follow customers up; hand the case to a colleague who does.").format(
				frappe.bold(get_fullname(to_user))
			)
		)
	doc.set(OWNER_FIELD, to_user)
	doc.flags.sp_owner_change_reasons = {OWNER_FIELD: (note or "").strip() or _("Hand over")}
	doc.flags.sp_hand_over = True
	# after the hand over the case is the colleague's: the giver may no longer write it
	doc.save(ignore_permissions=True)
	return doc.name


def owner_changed(case, old_owner: str | None) -> None:
	"""SP Case on_update, when the follow-up owner changed (hand over or admin reassign): the
	open call tasks move, the customer follows (unless featured), both owners are told, and an
	admin reassign is listed for review."""
	new_owner = case.get(OWNER_FIELD)
	for name in frappe.get_all(
		TASK,
		{"reference_doctype": CASE, "reference_name": case.name, "task_type": CALL_TASK, "status": TASK_OPEN},
		pluck="name",
	):
		frappe.db.set_value(TASK, name, "assigned_to", new_owner)
	if case.customer and not frappe.db.get_value("Customer", case.customer, "sp_featured"):
		frappe.db.set_value("Customer", case.customer, "sp_owner_user", new_owner)
	reason = (case.flags.sp_owner_change_reasons or {}).get(OWNER_FIELD) or ""
	by = get_fullname(frappe.session.user)
	customer = case.customer_name or case.customer
	if new_owner:
		_notify(case, new_owner, _("{0} gave you the case of {1}: {2}").format(by, customer, reason))
	if old_owner and old_owner != frappe.session.user:
		_notify(
			case,
			old_owner,
			_("{0} moved the case of {1} to {2}: {3}").format(by, customer, get_fullname(new_owner), reason),
		)
	if not case.flags.sp_hand_over:  # the admin's reassign is listed for review (RV2)
		from smart_power.sp_core.services.review import open_review_item

		open_review_item(
			category="Reassignment",
			reference_doctype=CASE,
			reference_name=case.name,
			summary=_("Case of {0} reassigned from {1} to {2}").format(
				customer, get_fullname(old_owner), get_fullname(new_owner)
			),
			reason=reason,
		)


@frappe.whitelist()
def hand_over_options(case: str) -> dict:
	"""F5: whether this user may hand the case over, and to whom (the other follow-up people)."""
	doc = frappe.get_doc(CASE, case)
	doc.check_permission("read")
	if not can_hand_over(doc):
		return {"allowed": False, "users": []}
	users = frappe.get_all(
		"Has Role", {"role": FOLLOWUP_ROLE, "parenttype": "User"}, pluck="parent", distinct=True
	)
	enabled = frappe.get_all(
		"User", {"name": ("in", users or [""]), "enabled": 1, "user_type": "System User"}, pluck="name"
	)
	return {
		"allowed": True,
		"users": [
			{"value": u, "label": get_fullname(u)} for u in sorted(enabled) if u != frappe.session.user
		],
	}
