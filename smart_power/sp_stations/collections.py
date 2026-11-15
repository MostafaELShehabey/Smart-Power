"""CL1 Collections (SP-81): every station I collect for, what is due and overdue, the cheques
due and who holds them, and my last contact; from here I call, record a payment (A2) or log a
received cheque.

A collection owner sees only the stations where they are the collection owner (a station handed
to them shows from the hand-over on). The admin and the accountant see every collection owner's
stations and may filter by owner.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_fullname

from smart_power.sp_stations.installments import OPEN_STATUSES, allocation, overdue_of

STATION, CHEQUE, CALL = "SP Station", "SP Cheque", "SP Call Log"
SEES_ALL = ("SP Admin", "System Manager", "SP Accountant")
OPEN_CHEQUES = ("Received", "Due", "Deposited", "Bounced")


def sees_all(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(SEES_ALL) & set(frappe.get_roles(user)))


@frappe.whitelist()
def collections(owner: str | None = None) -> dict:
	"""The stations to collect for: overdue first, then by the next due date."""
	user = frappe.session.user
	admin = sees_all(user)
	filters = {"status": ("in", OPEN_STATUSES)}
	if not admin:
		filters["collection_owner"] = user
	elif owner:
		filters["collection_owner"] = owner
	rows = [
		_station_row(frappe.get_doc(STATION, name)) for name in frappe.get_all(STATION, filters, pluck="name")
	]
	rows = [r for r in rows if r["remaining"] > 0 or r["cheques"]]
	rows.sort(key=lambda r: (-r["overdue_days"], str(r["next_due_date"] or "9999"), r["station"]))
	owners = []
	if admin:
		owners = [
			{"value": u, "label": get_fullname(u)}
			for u in sorted(
				set(frappe.get_all(STATION, {"status": ("in", OPEN_STATUSES)}, pluck="collection_owner"))
				- {None}
			)
		]
	return {
		"is_admin": admin,
		"owners": owners,
		"stations": rows,
		"totals": {
			"remaining": sum(r["remaining"] for r in rows),
			"overdue": sum(r["overdue_amount"] for r in rows),
			"overdue_stations": sum(1 for r in rows if r["overdue_amount"] > 0),
		},
	}


def _station_row(doc) -> dict:
	schedule = allocation(doc)
	overdue, days = overdue_of(schedule)
	last = frappe.get_all(
		CALL,
		{"station": doc.name},
		["call_time", "result", "note", "logged_by"],
		order_by="call_time desc",
		limit=1,
	)
	last = last[0] if last else None
	return {
		"station": doc.name,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"status": doc.status,
		"collection_owner": doc.collection_owner,
		"agreed": flt(doc.agreed_amount),
		"paid": flt(doc.paid_amount),
		"pending": flt(doc.pending_amount),
		"remaining": flt(doc.remaining_amount),
		"overdue_amount": overdue,
		"overdue_days": days,
		"next_due_date": doc.next_due_date,
		"next_due_amount": flt(doc.next_due_amount),
		"schedule": [
			{
				"due_date": r["due_date"],
				"amount": flt(r["payment_amount"]),
				"paid": r["paid"],
				"left": r["left"],
				"status": r["status"],
			}
			for r in schedule
		],
		"cheques": frappe.get_all(
			CHEQUE,
			{"station": doc.name, "status": ("in", OPEN_CHEQUES)},
			["name", "cheque_no", "amount", "due_date", "status", "holder"],
			order_by="due_date asc",
		),
		"last_contact": {
			"time": last.call_time,
			"result": frappe.db.get_value("SP List Value", last.result, "value_ar") or last.result,
			"note": last.note,
			"by": get_fullname(last.logged_by) if last.logged_by else "",
		}
		if last
		else None,
	}


@frappe.whitelist(methods=["POST"])
def log_call(station: str, result: str, note: str | None = None, next_call_at: str | None = None) -> str:
	"""Call: logged as a call on the station, by its collection owner or the admin."""
	owner = frappe.db.get_value(STATION, station, "collection_owner")
	if not owner:
		frappe.throw(_("Station {0} not found.").format(station))
	if owner != frappe.session.user and not sees_all():
		frappe.throw(_("Only the station's collection owner logs its calls."), frappe.PermissionError)
	call = frappe.get_doc(
		{"doctype": CALL, "station": station, "result": result, "note": note, "next_call_at": next_call_at}
	)
	call.flags.ignore_permissions = True  # checked above: the station's collection owner
	call.insert()
	return call.name
