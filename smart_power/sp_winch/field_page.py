"""The phone pages for light field entry (SP-180): what /sp-field asks the server for.

The winch operator, the Jumbo driver and the winch manager log on their phones, online, in their own
account: a job, an expense or money, saved as the same SP Field Entry as the desk (SP-108) through
field_entry.save_entry. The day still locks after its window (SP-109): a locked entry is read-only
and the only action left is to ask to reopen it. The Flutter app with offline sync is R2.

    options()                  the pickers: vehicles, job and expense types, methods, stations,
                               centers, official accounts, open outside jobs, today's bookings
    entries()                  my latest entries, locked or not, and any reopen request waiting
    entry(name)                one of my entries, to change it
    update_entry(name, values) change it while its day is open
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from smart_power.sp_winch import field_lock
from smart_power.sp_winch.bookings import FOR_OUTSIDE, _job_label, todays_jobs
from smart_power.sp_winch.field_entry import (
	ENTERED_FIELDS,
	ENTRY,
	JOB,
	LIST_VALUE,
	LOGS_FOR_OTHERS,
	OIL,
	OPERATOR_ROLES,
	WORKER_WAGE,
	_has_role,
)
from smart_power.sp_winch.receipts import OPEN, PARTIAL

LISTS = {"job_types": "Job Type", "expense_types": "Field Expense", "methods": "Payment Method"}
# what the phone may change on an entry it already saved
CHANGEABLE = tuple(f for f in ENTERED_FIELDS if f not in ("entry_kind", "client_uuid", "device_time"))
SHOWN = (
	"name",
	"entry_kind",
	"vehicle",
	"work_date",
	"status",
	"job_type",
	"expense_type",
	"money_kind",
	"customer_name",
	"station",
	"agreed_amount",
	"amount",
	"reopened",
)
MY_ENTRIES = field_lock.MY_ENTRIES


def _check() -> None:
	frappe.has_permission(ENTRY, "create", throw=True)


def _list(list_name: str) -> list[dict]:
	rows = frappe.get_all(
		LIST_VALUE,
		filters={"list_name": list_name, "is_active": 1},
		fields=["name", "code", "value_ar", "value_en"],
		order_by="sort_order asc, value_en asc",
	)
	arabic = frappe.local.lang == "ar"
	return [
		{
			"name": r.name,
			"code": r.code,
			"label": (r.value_ar if arabic else r.value_en) or r.value_ar or r.value_en,
		}
		for r in rows
	]


def _open_jobs(user: str) -> list[dict]:
	"""Outside jobs I logged or that were logged for me, with money still open: money is received on these."""
	rows = frappe.get_all(
		ENTRY,
		filters={"entry_kind": JOB, "for_kind": FOR_OUTSIDE, "payment_status": ("in", (OPEN, PARTIAL))},
		or_filters={"logged_by": user, "on_behalf_of": user},
		fields=["name", "customer_name", "work_date", "outstanding_amount"],
		order_by="work_date desc",
	)
	return [{**r, "outstanding": flt(r.outstanding_amount)} for r in rows]


@frappe.whitelist()
def options() -> dict:
	_check()
	from smart_power.sp_finance.accounts import OFFICIAL
	from smart_power.sp_finance.queries import CENTER_FIELDS

	user = frappe.session.user
	settings = frappe.get_cached_doc("Smart Power Settings")
	centers = [settings.get(f) for f in CENTER_FIELDS if settings.get(f)]
	centers += frappe.get_all("Vehicle", {"sp_cost_center": ("is", "set")}, pluck="sp_cost_center")
	operators = []
	if _has_role(LOGS_FOR_OTHERS):
		users = frappe.get_all(
			"Has Role", {"role": ("in", OPERATOR_ROLES), "parenttype": "User"}, pluck="parent"
		)
		operators = frappe.get_all(
			"User", {"name": ("in", users or [""]), "enabled": 1}, ["name", "full_name"], order_by="full_name"
		)
	return {
		"today": nowdate(),
		"lock_days": field_lock.lock_days(),
		"vehicles": frappe.get_all("Vehicle", fields=["name", "sp_vehicle_type"], order_by="name"),
		"my_vehicle": frappe.db.get_value("Vehicle", {"sp_driver_user": user}),
		**{key: _list(list_name) for key, list_name in LISTS.items()},
		"oil_code": OIL,
		"wage_code": WORKER_WAGE,
		"stations": frappe.get_all(
			"SP Station", {"status": ("!=", "Cancelled")}, ["name", "customer_name"], order_by="name"
		),
		"centers": sorted(set(centers)),
		"accounts": frappe.get_all(
			"Account",
			{"sp_account_kind": OFFICIAL, "is_group": 0, "disabled": 0},
			pluck="name",
			order_by="name",
		),
		"open_jobs": _open_jobs(user),
		"bookings": todays_jobs(user),
		"operators": operators,
	}


def _summary(row) -> str:
	if row.entry_kind == JOB:
		who = row.customer_name or row.station or ""
		return " · ".join(part for part in (_job_label(row.job_type), who) if part)
	if row.money_kind:
		return _(row.money_kind)
	return _job_label(row.expense_type)


@frappe.whitelist()
def entries() -> list[dict]:
	"""My latest entries; a locked one shows its lock, and the reopen request it waits for."""
	_check()
	user = frappe.session.user
	rows = frappe.get_all(
		ENTRY,
		or_filters={"logged_by": user, "on_behalf_of": user},
		fields=list(SHOWN),
		order_by="work_date desc, creation desc",
		limit=MY_ENTRIES,
	)
	out = []
	for r in rows:
		locked = field_lock.is_locked(r.vehicle, r.work_date)
		request = (
			frappe.db.get_value(
				field_lock.REQUEST,
				{"vehicle": r.vehicle, "work_date": r.work_date, "status": field_lock.OPEN},
			)
			if locked
			else None
		)
		out.append(
			{
				"name": r.name,
				"entry_kind": r.entry_kind,
				"vehicle": r.vehicle,
				"work_date": r.work_date,
				"status": r.status,
				"summary": _summary(r),
				"amount": flt(r.agreed_amount if r.entry_kind == JOB else r.amount),
				"locked": locked,
				"request": request,
				"reopened": r.reopened,
			}
		)
	return out


def _mine(name: str):
	doc = frappe.get_doc(ENTRY, name)
	doc.check_permission("write")
	return doc


@frappe.whitelist()
def entry(name: str) -> dict:
	"""One of my entries, as the form shows it; read-only once its day is locked."""
	_check()
	doc = _mine(name)
	return {
		"name": doc.name,
		"entry_kind": doc.entry_kind,
		**{f: doc.get(f) for f in CHANGEABLE},
		"locked": field_lock.is_locked(doc.vehicle, doc.work_date),
	}


@frappe.whitelist(methods=["POST"])
def update_entry(name: str, values: str | dict) -> str:
	"""Change one of my entries. The lock refuses it once the day has closed (SP-109)."""
	_check()
	values = frappe.parse_json(values) or {}
	unknown = set(values) - set(CHANGEABLE)
	if unknown:
		frappe.throw(_("{0} cannot be changed here.").format(", ".join(sorted(unknown))))
	doc = _mine(name)
	doc.update(values)
	doc.save()
	return doc.name
