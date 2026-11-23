"""C4 Site survey (SP-95): the well data or load table, pin and photos of a request that needs a
site visit.

    ask(case)          one open survey per request, and a "Site Survey" task for each surveyor
                       (installation managers and the site survey role); called when a request is
                       saved with "site visit needed", and by Q3's "ask survey"
    complete(name)     the surveyor submits: the data joins the request (the case, where the
                       request lives, SP-47), what it replaced is kept on the survey and in a
                       comment on the case, the tasks close and the quote creator (or, before one
                       took the request, every quote creator) is told

The survey carries the customer's name, mobile and location itself: a surveyor cannot open the
case. Only the fields the case's system type asks for are copied into its Request Details; the
rest (the well's yield, say) stays on the survey. `client_uuid` and `device_time` are for the
mobile app's offline sync (SP-152).
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

SURVEY, CASE, TASK = "SP Site Survey", "SP Case", "SP Task"
OPEN, DONE = "Open", "Done"
TASK_TYPE = "Site Survey"
SURVEYOR_ROLES = ("SP Installation Manager", "SP Site Survey")
ADMIN_ROLES = ("SP Admin", "System Manager")
QUOTE_CREATOR_ROLE = "SP Quote Creator"
EVENT = "survey_done"
# survey field → the request detail it fills
WELL_FIELDS = (
	("well_depth", "well_depth_m", "Well Depth (m)"),
	("water_level", "water_level_m", "Water Level (m)"),
	("pump_depth", "pump_depth_m", "Pump Depth (m)"),
	("yield_m3h", "yield_m3h", "Well Yield (m³/h)"),
)
LOAD_KEYS = ("device", "qty", "watts", "day_hours", "night_hours")


def surveyors() -> list[str]:
	from smart_power.sp_sales.quote_request import _users_with

	return sorted({u for role in SURVEYOR_ROLES for u in _users_with(role)})


def open_survey(case: str) -> str | None:
	return frappe.db.get_value(SURVEY, {"case": case, "status": OPEN})


def _system_type(case) -> str | None:
	return case.system_types[0].system_type if case.get("system_types") else None


def ask(case) -> str:
	"""The request's open survey (made when there is none), with a task for each surveyor."""
	from smart_power.sp_core.inbox import create_task

	existing = open_survey(case.name)
	if existing:
		return existing
	doc = frappe.get_doc({"doctype": SURVEY, "case": case.name})
	doc.flags.ignore_permissions = True
	doc.insert()
	create_task(
		TASK_TYPE,
		SURVEY,
		doc.name,
		surveyors(),
		_("Site survey for {0}").format(case.customer_name or case.customer),
		due_at=case.get("quote_due_at"),
	)
	return doc.name


def validate(doc) -> None:
	before = doc.get_doc_before_save()
	if before and before.status == DONE and not doc.flags.sp_complete:
		frappe.throw(_("The survey is submitted: it no longer changes."))
	if not doc.flags.sp_complete:
		doc.status = before.status if before else OPEN
	case = frappe.db.get_value(CASE, doc.case, ["customer_name", "mobile", "location_text"], as_dict=True)
	if case:
		doc.customer_name, doc.mobile = case.customer_name, case.mobile
		doc.location_text = case.location_text
	system_type = frappe.db.get_value(
		"SP Case System Type", {"parent": doc.case}, "system_type", order_by="idx asc"
	)
	doc.system_type = frappe.db.get_value("SP List Value", system_type, "value_ar") if system_type else None
	for fieldname, _key, label in WELL_FIELDS:
		if flt(doc.get(fieldname)) < 0:
			frappe.throw(_("{0} cannot be negative.").format(_(label)))


@frappe.whitelist(methods=["POST"])
def complete(name: str) -> dict:
	"""The surveyor submits the survey: its data joins the request."""
	doc = frappe.get_doc(SURVEY, name)
	doc.check_permission("write")
	if doc.status == DONE:
		frappe.throw(_("The survey is already submitted."))
	if not any(flt(doc.get(f)) for f, _k, _l in WELL_FIELDS) and not doc.loads:
		frappe.throw(_("Enter the well data or the load table first."))
	differences = _join_request(doc)
	doc.status, doc.surveyed_by, doc.surveyed_at = DONE, frappe.session.user, now_datetime()
	doc.differences = "\n".join(differences) or None
	doc.flags.sp_complete = True
	doc.save()
	_close_tasks(doc.name)
	_notify(doc)
	return {"status": doc.status, "differences": differences}


def _join_request(doc) -> list[str]:
	"""Copy the survey into the case; returns what it replaced, line by line."""
	from smart_power.sp_sales.quote_request import request_fields

	case = frappe.get_doc(CASE, doc.case)
	raw = case.request_details
	details = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
	asked = {f["fieldname"] for f in request_fields(_system_type(case))}
	differences = []
	for fieldname, key, label in WELL_FIELDS:
		value = flt(doc.get(fieldname))
		if not value or key not in asked:
			continue
		old = details.get(key)
		if old not in (None, "") and flt(old) != value:
			differences.append(_("{0}: {1} → {2}").format(_(label), flt(old), value))
		details[key] = value
	case.request_details = json.dumps(details, ensure_ascii=False) if details else None
	if doc.loads:
		new = [{k: row.get(k) for k in LOAD_KEYS} for row in doc.loads]
		old = [{k: row.get(k) for k in LOAD_KEYS} for row in case.loads]
		if old and old != new:
			differences.append(_("Load table: {0} rows replaced by {1}").format(len(old), len(new)))
		case.set("loads", new)
	if doc.geo:
		if case.geo and case.geo != doc.geo:
			differences.append(_("Location pin replaced"))
		case.geo = doc.geo
	case.flags.ignore_permissions = True
	case.flags.ignore_validate = True  # the request's own rules are for its form, not the survey
	case.save()
	if differences:
		case.add_comment(
			"Comment", _("Site survey {0} replaced: {1}").format(doc.name, "; ".join(differences))
		)
	return differences


def _close_tasks(name: str) -> None:
	from smart_power.sp_core.inbox import close_tasks

	close_tasks(SURVEY, name, TASK_TYPE)


def _notify(doc) -> None:
	from smart_power.notify import send
	from smart_power.sp_sales.quote_request import _users_with

	creator = frappe.db.get_value(CASE, doc.case, "quote_creator")
	users = [creator] if creator else _users_with(QUOTE_CREATOR_ROLE)
	send(
		EVENT,
		users,
		CASE,
		doc.case,
		_("Site survey done for {0}").format(doc.customer_name or doc.case),
		from_user=frappe.session.user,
	)
