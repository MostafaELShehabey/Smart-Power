"""Winch and car bookings (SP-107, W1): every job planned and priced before it happens.

A booking is for a station, an outside customer or one of Smart Power's own centers. It stays
Expected until it has a vehicle, a job type, a place, a date and an operator; then it is Booked and
the operator is told. A contract with a winch line opens an Expected booking of that amount.

    expect_winch_job(station, amount)   the contract's winch line
    todays_jobs(user)                   what the operator's field page shows today

The job is logged, marked Done and charged from light field entry (SP-108). Winch receipts drive
the payment status (SP-112).
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from smart_power.notify import send

BOOKING, STATION, EMPLOYEE, LIST_VALUE = "SP Vehicle Booking", "SP Station", "Employee", "SP List Value"
EXPECTED, BOOKED, DONE, CANCELLED = "Expected", "Booked", "Done", "Cancelled"
FOR_STATION, FOR_OUTSIDE, FOR_CENTER = "Station", "Outside", "Internal center"
MANUAL, TRANSFER, CONTRACT = "Manual", "Transfer", "Contract"
OPERATOR_ROLES = ("SP Driver", "SP Winch Operator")
MANAGERS = ("SP Winch Manager", "SP Admin", "System Manager")
EVENT_ASSIGNED = "booking_assigned"
ACTIVE = "Active"


def _required(doc, fields: dict) -> None:
	for fieldname, label in fields.items():
		if not doc.get(fieldname):
			frappe.throw(_("Enter the {0}.").format(_(label)), frappe.MandatoryError)


def _set_party(doc) -> None:
	"""Only what belongs to who the job is for is kept."""
	if doc.for_kind == FOR_STATION:
		_required(doc, {"station": "Station"})
		doc.update({"customer_name": None, "customer_phone": None, "internal_center": None})
		if not flt(doc.agreed_amount) and doc.source != TRANSFER:
			doc.agreed_amount = flt(frappe.db.get_value(STATION, doc.station, "winch_expected_amount"))
	elif doc.for_kind == FOR_OUTSIDE:
		_required(doc, {"customer_name": "Customer Name", "customer_phone": "Customer Phone"})
		doc.update({"station": None, "internal_center": None})
	else:
		_required(doc, {"internal_center": "Requesting Center"})
		doc.update({"station": None, "customer_name": None, "customer_phone": None})


def _default_operator(doc) -> None:
	"""The vehicle's own driver, when the booking names nobody."""
	if doc.operator or not doc.vehicle:
		return
	driver = frappe.db.get_value("Vehicle", doc.vehicle, "sp_driver_user")
	if driver:
		doc.operator = frappe.db.get_value(EMPLOYEE, {"user_id": driver, "status": ACTIVE})


def validate(doc) -> None:
	if flt(doc.agreed_amount) < 0:
		frappe.throw(_("The agreed amount cannot be negative."))
	_set_party(doc)
	_default_operator(doc)
	if doc.status in (DONE, CANCELLED):
		return
	ready = all((doc.vehicle, doc.job_type, doc.place, doc.planned_date, doc.operator))
	doc.status = BOOKED if ready else EXPECTED


def _user_of(employee: str | None) -> str | None:
	return frappe.db.get_value(EMPLOYEE, employee, "user_id") if employee else None


def on_update(doc) -> None:
	"""The operator hears about a job when it is booked for them."""
	before = doc.get_doc_before_save()
	newly = doc.status == BOOKED and (
		not before or before.status != BOOKED or before.operator != doc.operator
	)
	user = _user_of(doc.operator)
	if newly and user:
		subject = _("New job {0} on {1}: {2}").format(doc.name, doc.planned_date, doc.place)
		send(EVENT_ASSIGNED, [user], BOOKING, doc.name, subject)


def expect_winch_job(station: str, amount: float) -> str | None:
	"""The contract's winch line: one Expected booking for the station, kept at the line's amount."""
	found = frappe.db.get_value(
		BOOKING,
		{"station": station, "source": CONTRACT, "status": ("!=", CANCELLED)},
		["name", "status"],
		as_dict=True,
	)
	if found:
		if found.status == EXPECTED:
			frappe.db.set_value(BOOKING, found.name, "agreed_amount", flt(amount))
		return found.name
	winch = frappe.db.get_value("Vehicle", {"sp_vehicle_type": "Winch"})
	doc = frappe.get_doc(
		{
			"doctype": BOOKING,
			"for_kind": FOR_STATION,
			"station": station,
			"vehicle": winch,
			"agreed_amount": flt(amount),
			"source": CONTRACT,
		}
	)
	doc.flags.ignore_permissions = True  # the contract's maker opens it, whoever they are
	doc.insert()
	return doc.name


def expect_transfer_job(transfer: str, station: str, kind: str, day) -> str:
	"""A transfer order's transport: an Expected booking for the winch manager to assign (SP-88)."""
	doc = frappe.get_doc(
		{
			"doctype": BOOKING,
			"for_kind": FOR_STATION,
			"station": station,
			"vehicle": frappe.db.get_value("Vehicle", {"sp_vehicle_type": kind}),
			"job_type": frappe.db.get_value(LIST_VALUE, {"list_name": "Job Type", "code": "TRANSPORT"}),
			"planned_date": day,
			"agreed_amount": 0,
			"source": TRANSFER,
			"transfer_order": transfer,
		}
	)
	doc.flags.ignore_permissions = True  # purchasing opens it with the transfer
	doc.insert()
	return doc.name


def cancel_transfer_job(transfer: str) -> None:
	"""A cancelled transfer needs no transport, unless the job has already been done."""
	for name in frappe.get_all(
		BOOKING, {"transfer_order": transfer, "status": ("in", (EXPECTED, BOOKED))}, pluck="name"
	):
		frappe.db.set_value(BOOKING, name, "status", CANCELLED)


def _check_manager() -> None:
	user = frappe.session.user
	if user != "Administrator" and not set(MANAGERS) & set(frappe.get_roles(user)):
		frappe.throw(_("Only the winch manager changes bookings."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def cancel_booking(name: str) -> str:
	_check_manager()
	doc = frappe.get_doc(BOOKING, name)
	if doc.status == DONE:
		frappe.throw(_("A finished job cannot be cancelled."))
	doc.db_set("status", CANCELLED)
	return doc.name


def _job_label(job_type: str | None) -> str:
	if not job_type:
		return ""
	row = frappe.db.get_value(LIST_VALUE, job_type, ["value_ar", "value_en"], as_dict=True) or {}
	first, second = (row.get("value_ar"), row.get("value_en"))
	return (first if frappe.local.lang == "ar" else second) or first or second or job_type


def todays_jobs(user: str | None = None) -> list[dict]:
	"""The operator's booked jobs for today. A price shows only where they collect it."""
	user = user or frappe.session.user
	employee = frappe.db.get_value(EMPLOYEE, {"user_id": user})
	if not employee:
		return []
	rows = frappe.get_all(
		BOOKING,
		{"operator": employee, "planned_date": nowdate(), "status": BOOKED},
		[
			"name",
			"vehicle",
			"job_type",
			"place",
			"for_kind",
			"station",
			"internal_center",
			"customer_name",
			"customer_phone",
			"agreed_amount",
		],
		order_by="creation asc",
	)
	return [
		{
			"name": r.name,
			"vehicle": r.vehicle,
			"job": _job_label(r.job_type),
			"place": r.place,
			"who": r.customer_name or r.station or _("Smart Power"),
			"phone": r.customer_phone,
			"amount": flt(r.agreed_amount) if r.for_kind == FOR_OUTSIDE else None,
			# what "Log this job" fills on the phone form (BUG-16); the server fills the same on save
			"job_type": r.job_type,
			"for_kind": r.for_kind,
			"station": r.station,
			"internal_center": r.internal_center,
			"customer_name": r.customer_name,
		}
		for r in rows
	]


@frappe.whitelist()
def operator_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | str | None = None
) -> list:
	"""Active employees who drive: the people a job can be booked for."""
	_check_manager()
	users = frappe.get_all("Has Role", {"role": ("in", OPERATOR_ROLES), "parenttype": "User"}, pluck="parent")
	return frappe.get_all(
		EMPLOYEE,
		filters={"status": ACTIVE, "user_id": ("in", users or [""])},
		or_filters={"name": ("like", f"%{txt}%"), "employee_name": ("like", f"%{txt}%")},
		fields=["name", "employee_name"],
		as_list=True,
		start=start,
		page_length=page_len,
	)


@frappe.whitelist()
def station_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | str | None = None
) -> list:
	"""Open stations, for a job booked by the winch manager."""
	_check_manager()
	return frappe.get_all(
		STATION,
		filters={"status": ("!=", "Cancelled")},
		or_filters={"name": ("like", f"%{txt}%"), "customer_name": ("like", f"%{txt}%")},
		fields=["name", "customer_name"],
		as_list=True,
		start=start,
		page_length=page_len,
	)
