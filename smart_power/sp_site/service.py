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

SV2 Service and warranty (SP-99) adds, on the same ticket:

    work log           each remote call or site visit: the work done, the hours, and a part. Only
                       installations log work, and a logged part line no longer changes.
    parts              a part is issued from stock when its line is saved (the main store unless
                       another warehouse is chosen), as a Material Issue on the station's project,
                       so its cost is the station's. Out of warranty, the line's charge becomes a
                       draft income record (type Service Charge) for the accountant to complete
                       with the account the money came in through (owner, 2026-11-23).
    SP Supplier Claim  a claim to the supplier for a covered component: record-only, no entry.
"""

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate, now_datetime, today

TICKET, STATION, WARRANTY, TASK_TYPE = "SP Service Ticket", "SP Station", "SP Warranty", "Service Ticket"
ISSUE_LIST = "Service Issue"
CLAIM, RECORD = "SP Supplier Claim", "SP Simple Record"
CHARGE_TYPE = ("Simple Record Type", "SERVICE_CHARGE")
ACCOUNTANT_ROLES = ("SP Accountant", "SP Admin")
LOCKED_FIELDS = ("work_date", "item", "qty", "warehouse", "serial_no", "in_warranty", "charge_amount")
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
	doc.company = frappe.db.get_value(STATION, doc.station, "company")
	_validate_work(doc)
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


# --- SV2: the work log, parts and supplier claims (SP-99) -------------------------------------------


def _validate_work(doc) -> None:
	"""Only installations log work; a line whose part was issued, or was charged, stays as it is."""
	from smart_power.sp_stock.warehouses import MAIN, warehouse_of

	before = None if doc.is_new() else doc.get_doc_before_save()
	old = {r.name: r for r in (before.work_log if before else [])}
	now = {r.name for r in doc.work_log}
	changed = len(now) != len(old) or any(r.name not in old for r in doc.work_log)
	for name, row in old.items():
		if name not in now and (row.stock_entry or row.income_record):
			frappe.throw(
				_("Work line {0} has a part issued or a charge: it cannot be removed.").format(row.idx)
			)
	for row in doc.work_log:
		was = old.get(row.name)
		if was:
			row.stock_entry, row.income_record, row.logged_by = (
				was.stock_entry,
				was.income_record,
				was.logged_by,
			)
			posted = was.stock_entry or was.income_record
			if posted and any((was.get(f) or None) != (row.get(f) or None) for f in LOCKED_FIELDS):
				frappe.throw(
					_("Work line {0} has a part issued or a charge: it no longer changes.").format(row.idx)
				)
			changed = changed or any(
				(was.get(f) or None) != (row.get(f) or None) for f in (*LOCKED_FIELDS, "notes", "hours")
			)
		else:
			row.stock_entry = row.income_record = None
			row.logged_by = frappe.session.user
		if row.item:
			if flt(row.qty) <= 0:
				frappe.throw(_("Work line {0}: enter the part's quantity.").format(row.idx))
			row.warehouse = row.warehouse or warehouse_of(doc.company, MAIN)
			if not row.warehouse:
				frappe.throw(_("Work line {0}: choose the warehouse the part comes from.").format(row.idx))
		if row.in_warranty:
			row.charge_amount = 0
		if flt(row.charge_amount) < 0 or flt(row.hours) < 0:
			frappe.throw(_("Work line {0}: the amounts cannot be negative.").format(row.idx))
	if changed and not is_installer():
		frappe.throw(_("Only installations log service work."), frappe.PermissionError)
	if changed and doc.status in (OPEN, CLOSED) and not doc.flags.sp_move:
		frappe.throw(_("Accept the ticket before logging work."))


def on_update(doc) -> None:
	"""Issue each new part from stock, and raise each new charge as a draft income record."""
	for row in doc.work_log:
		if row.item and not row.stock_entry:
			row.db_set("stock_entry", _issue_part(doc, row), update_modified=False)
		if flt(row.charge_amount) > 0 and not row.income_record:
			row.db_set("income_record", _charge(doc, row), update_modified=False)


def _issue_part(doc, row) -> str:
	from smart_power.sp_site.site_log import issue_materials

	project = frappe.db.get_value(STATION, doc.station, "project")
	if not project:
		frappe.throw(_("Station {0} has no project to charge.").format(doc.station))
	return issue_materials(
		doc.company,
		row.warehouse,
		project,
		[{"item_code": row.item, "qty": row.qty, "serial_no": row.serial_no}],
		row.work_date,
		_("Service part on ticket {0}").format(doc.name),
	)


def _charge(doc, row) -> str:
	"""A draft income record for the accountant: they choose the account the money came through."""
	from smart_power.sp_core.inbox import create_task
	from smart_power.sp_sales.quote_request import _users_with

	record_type = frappe.db.get_value("SP List Value", {"list_name": CHARGE_TYPE[0], "code": CHARGE_TYPE[1]})
	if not record_type:
		frappe.throw(_("The list Simple Record Type has no Service Charge value."))
	record = frappe.get_doc(
		{
			"doctype": RECORD,
			"work_date": row.work_date,
			"record_type": record_type,
			"amount": flt(row.charge_amount),
			"direction": "None",
			"station": doc.station,
			"company": doc.company,
			"note": _(
				"Service charge on ticket {0} ({1}): choose Money In and the account, then submit."
			).format(doc.name, doc.customer_name or doc.customer),
		}
	)
	record.flags.ignore_permissions = True
	record.insert()
	accountants = sorted({u for role in ACCOUNTANT_ROLES for u in _users_with(role)})
	create_task(
		"Other",
		RECORD,
		record.name,
		accountants,
		_("Service charge {0} to record for ticket {1}").format(
			frappe.format(row.charge_amount, "Currency"), doc.name
		),
		amount=flt(row.charge_amount),
	)
	return record.name


def validate_claim(doc) -> None:
	"""A supplier claim: its station and the component's warranty end come from the register."""
	ticket = frappe.db.get_value(TICKET, doc.ticket, ["station"], as_dict=True)
	doc.station = ticket.station if ticket else None
	doc.warranty_end = None
	if doc.serial_no:
		doc.warranty_end = frappe.db.get_value(
			WARRANTY, {"serial_no": doc.serial_no, "station": doc.station, "status": "Active"}, "end_date"
		)
