"""SV1 Service ticket (SP-72): follow-up opens a ticket for one of the customer's stations, and
installations act on it.

    warranty_for(station, on)   each registered component of the station (SP Warranty, SP-179)
                                with its end date and whether it is covered on that day, and the
                                station's overall status: In warranty, Partly, Out, Not registered
    after_insert                a "Service Ticket" task for each installation manager and warranty
                                technician, and a notification (pushed, like every event, by each
                                user's preferences)
    move(name, status)          Open → Accepted → In progress → Closed, by installations; whoever
                                opened the ticket is told at every step

The work log, parts and supplier claims are SP-99.
"""

import frappe
from frappe import _
from frappe.utils import formatdate, getdate, now_datetime, today

TICKET, STATION, WARRANTY, TASK_TYPE = "SP Service Ticket", "SP Station", "SP Warranty", "Service Ticket"
ISSUE_LIST = "Service Issue"
OPEN, ACCEPTED, IN_PROGRESS, CLOSED = "Open", "Accepted", "In progress", "Closed"
NEXT = {OPEN: ACCEPTED, ACCEPTED: IN_PROGRESS, IN_PROGRESS: CLOSED}
IN, PARTLY, OUT, NONE = "In warranty", "Partly in warranty", "Out of warranty", "Not registered"
INSTALLER_ROLES = ("SP Installation Manager", "SP Warranty Service")
ADMIN_ROLES = ("SP Admin", "System Manager")
NEW_EVENT, STATUS_EVENT = "service_ticket", "service_ticket_status"


def is_installer(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(INSTALLER_ROLES + ADMIN_ROLES) & set(frappe.get_roles(user)))


def installers() -> list[str]:
	from smart_power.sp_sales.quote_request import _users_with

	return sorted({u for role in INSTALLER_ROLES for u in _users_with(role)})


def warranty_for(station: str, on=None) -> dict:
	"""{status, components: [{serial_no, item, item_name, end_date, covered}]} on a day."""
	day = getdate(on or today())
	rows = frappe.get_all(
		WARRANTY,
		{"station": station, "status": "Active"},
		["serial_no", "item", "item_name", "end_date", "months"],
		order_by="item asc, serial_no asc",
	)
	components = [{**r, "covered": bool(r.end_date and getdate(r.end_date) >= day)} for r in rows]
	covered = sum(1 for c in components if c["covered"])
	status = NONE if not components else IN if covered == len(components) else OUT if not covered else PARTLY
	return {"status": status, "components": components}


def validate(doc) -> None:
	if doc.is_new():
		doc.status, doc.opened_by = OPEN, frappe.session.user
	else:
		before = doc.get_doc_before_save()
		if before and not doc.flags.sp_move:
			doc.status, doc.closed_at, doc.assigned_to = before.status, before.closed_at, before.assigned_to
		if before and before.status == CLOSED and not doc.flags.sp_move:
			frappe.throw(_("The ticket is closed: it no longer changes."))
	if frappe.db.get_value(STATION, doc.station, "customer") != doc.customer:
		frappe.throw(_("Station {0} is not one of this customer's stations.").format(doc.station))
	if frappe.db.get_value("SP List Value", doc.issue_type, "list_name") != ISSUE_LIST:
		frappe.throw(_("{0} is not a service issue.").format(doc.issue_type))
	if not doc.warranty_status or doc.is_new():
		_set_warranty(doc)


def _set_warranty(doc) -> None:
	cover = warranty_for(doc.station)
	doc.warranty_status = cover["status"]
	doc.warranty_details = "\n".join(
		_("{0} ({1}): {2} until {3}").format(
			c["item_name"] or c["item"] or "",
			c["serial_no"],
			_(IN) if c["covered"] else _(OUT),
			formatdate(c["end_date"]) if c["end_date"] else "",
		)
		for c in cover["components"]
	)


def _subject(doc) -> str:
	issue = frappe.db.get_value("SP List Value", doc.issue_type, "value_ar") or doc.issue_type
	return _("Service ticket {0}: {1} at station {2} ({3})").format(
		doc.name, issue, doc.station, doc.customer_name or doc.customer
	)


def after_insert(doc) -> None:
	from smart_power.notify import send
	from smart_power.sp_core.inbox import HIGH, create_task

	users = installers()
	create_task(
		TASK_TYPE,
		TICKET,
		doc.name,
		users,
		_subject(doc),
		description=doc.description,
		**({"priority": HIGH} if doc.urgency == "Urgent" else {}),
	)
	send(NEW_EVENT, users, TICKET, doc.name, _subject(doc), from_user=frappe.session.user)


@frappe.whitelist(methods=["POST"])
def move(name: str, status: str) -> str:
	"""Installations move the ticket one step; the one who opened it is told."""
	from smart_power.notify import send
	from smart_power.sp_core.inbox import close_tasks

	if not is_installer():
		frappe.throw(_("Only installations move a service ticket."), frappe.PermissionError)
	doc = frappe.get_doc(TICKET, name)
	if NEXT.get(doc.status) != status:
		frappe.throw(_("A ticket that is {0} cannot become {1}.").format(_(doc.status), _(status)))
	doc.status = status
	if status == ACCEPTED:
		doc.assigned_to = frappe.session.user
	if status == CLOSED:
		doc.closed_at = now_datetime()
	doc.flags.sp_move = True
	doc.flags.ignore_permissions = True
	doc.save()
	if status == CLOSED:
		close_tasks(TICKET, doc.name, TASK_TYPE)
	send(
		STATUS_EVENT,
		[doc.opened_by],
		TICKET,
		doc.name,
		_("Service ticket {0} is now {1}").format(doc.name, _(status)),
		from_user=frappe.session.user,
	)
	return status
