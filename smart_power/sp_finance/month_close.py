"""A14 Month close (SP-126): a checklist with live status, then the month is locked.

    checklist(company, month)    the live checks: confirmations cleared, transit reviewed, cheques
                                 updated, indirect pool split, team commission (R5), entries
                                 reviewed. Each: status Green / Red / Grey, the count, a link.
    close_month(...)             the admin closes an ended month; a red check needs a reason
                                 (owner, 2026-11-22). ERPNext's Accounting Period for the month
                                 closes every voucher type that posts, with no exempt role: any
                                 entry dated in it is refused, for the admin too.
    reopen_month(...)            the admin only, with a reason (audited): the period is disabled.

The SP records that post on their own date are refused too while their month is closed (guard),
so nothing waits to post into a closed month. "Team commission entered" waits on R5 (SP-143): it
shows, but never blocks (owner, 2026-11-22).
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, get_first_day, get_last_day, getdate, now_datetime, today

CLOSE, PERIOD, CHEQUE, REVIEW = "SP Month Close", "Accounting Period", "SP Cheque", "SP Review Item"
OPEN, CLOSED = "Open", "Closed"
GREEN, RED, GREY = "Green", "Red", "Grey"
ADMIN_ROLES = ("SP Admin", "System Manager")
PERIOD_PREFIX = "SP"
# the SP records that post on their own date (SP-126 guard): doctype -> date field
GUARDED = {
	"SP Customer Payment": "work_date",
	"SP Transfer": "work_date",
	"SP Expense": "work_date",
	"SP Cash Box Day": "day",
	"SP Indirect Split": "month",
}


def _check_admin() -> None:
	if frappe.session.user != "Administrator" and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin closes or reopens a month."), frappe.PermissionError)


def _bounds(month) -> tuple:
	start = get_first_day(getdate(month))
	return start, get_last_day(start)


def _company(company: str | None) -> str:
	from smart_power.sp_core.services.company import COMPANY_SETTINGS

	return (
		company
		or frappe.defaults.get_user_default("company")
		or frappe.db.get_single_value(COMPANY_SETTINGS, "company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)


# --- the checks ---------------------------------------------------------------------------------


def _row(ok: bool, count: int, details: str = "", route=None, blocking: bool = True) -> dict:
	return {
		"status": GREEN if ok else (RED if blocking else GREY),
		"count": count,
		"details": details,
		"route": route,
		"blocking": blocking,
	}


def check_confirmations(company, start, end) -> dict:
	"""No pending item dated in the month (A1)."""
	from smart_power.sp_finance.confirmations import pending

	items = [
		i
		for i in pending({"from_date": str(start), "to_date": str(end)})["items"]
		if i.get("date") and start <= getdate(i["date"]) <= end
	]
	names = ", ".join(i["name"] for i in items[:10])  # sp-allow-number: names shown in the row
	return _row(
		not items,
		len(items),
		names,
		{"route": ["sp-confirmations"], "options": {"from_date": str(start), "to_date": str(end)}},
	)


def check_transit(company, start, end) -> dict:
	"""No transit account holding the month's cash past its limit (SP-116)."""
	from smart_power.sp_finance.transit import limit_days, oldest_open_date, transit_accounts

	late = []
	for acc in transit_accounts():
		if acc.company != company:
			continue
		oldest, days = oldest_open_date(acc.name), limit_days(acc.name)
		if oldest and days and oldest <= end and (getdate(today()) - oldest).days + 1 > days:
			late.append(acc.account_name)
	return _row(not late, len(late), ", ".join(late), {"route": ["sp-treasury"]})


def check_cheques(company, start, end) -> dict:
	"""No cheque due by the month's end still Received or Due (SP-118)."""
	from smart_power.sp_finance.cheques import DUE, RECEIVED

	filters = {"status": ("in", (RECEIVED, DUE)), "due_date": ("<=", str(end))}
	if frappe.get_meta(CHEQUE).has_field("company"):
		filters["company"] = company
	names = frappe.get_all(CHEQUE, filters, pluck="name")
	return _row(
		not names,
		len(names),
		", ".join(names[:10]),  # sp-allow-number: names shown in the row
		{"route": ["List", CHEQUE], "options": {"name": ["in", names]}} if names else None,
	)


def check_indirect(company, start, end) -> dict:
	"""The month's indirect pool is split into its closed stations (SP-124)."""
	from smart_power.sp_finance.indirect_split import pool_amount

	pool = pool_amount(company, start)
	split = frappe.db.exists(
		"SP Indirect Split", {"company": company, "month": ("between", [start, end]), "docstatus": 1}
	)
	ok = not pool or bool(split)
	return _row(
		ok,
		0 if ok else 1,
		"" if ok else _("Pool of {0} not split yet.").format(frappe.format(pool, "Currency")),
		{"route": ["List", "SP Indirect Split"]},
	)


def check_commission(company, start, end) -> dict:
	"""R5 team commission is SP-143's: shown, never blocking (owner, 2026-11-22)."""
	return _row(False, 0, _("Waits on R5 team commission (SP-143)."), None, blocking=False)


def check_reviews(company, start, end) -> dict:
	"""The month's review items (RV2) are marked reviewed."""
	names = frappe.get_all(
		REVIEW,
		{"status": "Open", "creation": ("between", [f"{start} 00:00:00", f"{end} 23:59:59"])},
		pluck="name",
	)
	return _row(not names, len(names), "", {"route": ["sp-review-centre"]})


CHECKS = (
	("confirmations", "Confirmations cleared", check_confirmations),
	("transit", "Transit reviewed", check_transit),
	("cheques", "Cheques updated", check_cheques),
	("indirect", "Indirect pool split", check_indirect),
	("commission", "Team commission entered (R5)", check_commission),
	("reviews", "Entries reviewed", check_reviews),
)


def run_checks(company: str, month) -> list[dict]:
	start, end = _bounds(month)
	return [{"key": key, "label": _(label), **fn(company, start, end)} for key, label, fn in CHECKS]


# --- the record and the period ------------------------------------------------------------------


def _record(company: str, month) -> str | None:
	return frappe.db.get_value(CLOSE, {"company": company, "month": _bounds(month)[0]})


def period_name(company: str, month) -> str:
	return f"{PERIOD_PREFIX} {_bounds(month)[0].strftime('%Y-%m')}"


def _period(company: str, month) -> str | None:
	start, end = _bounds(month)
	return frappe.db.get_value(PERIOD, {"company": company, "start_date": start, "end_date": end})


def is_closed(company: str | None, day) -> bool:
	"""A month is closed when its Accounting Period is on."""
	if not company or not day:
		return False
	day = getdate(day)
	return bool(
		frappe.db.exists(
			PERIOD,
			{"company": company, "disabled": 0, "start_date": ("<=", day), "end_date": (">=", day)},
		)
	)


@frappe.whitelist()
def checklist(month: str | None = None, company: str | None = None) -> dict:
	"""A14: the month's checks, live, and how the month stands."""
	_check_admin()
	company = _company(company)
	month = _bounds(month or add_months(today(), -1))[0]
	name = _record(company, month)
	doc = frappe.get_doc(CLOSE, name) if name else None
	return {
		"company": company,
		"month": str(month),
		"ended": _bounds(month)[1] < getdate(today()),
		"status": doc.status if doc else OPEN,
		"name": name,
		"closed_by": doc.closed_by if doc else None,
		"closed_on": doc.closed_on if doc else None,
		"checks": run_checks(company, month),
		"closed_checks": [r.as_dict() for r in doc.checks] if doc else [],
		"reopens": [r.as_dict() for r in doc.reopens] if doc else [],
	}


@frappe.whitelist(methods=["POST"])
def close_month(month: str, company: str | None = None, reasons: str | dict | None = None) -> str:
	"""Close an ended month: every red check needs its reason; the Accounting Period locks it."""
	from smart_power.sp_core.services.audit import audit

	_check_admin()
	company = _company(company)
	start, end = _bounds(month)
	if end >= getdate(today()):
		frappe.throw(_("A month can be closed only after it ends."))
	if is_closed(company, start):
		frappe.throw(_("{0} is already closed.").format(start.strftime("%m-%Y")))
	reasons = {k: (v or "").strip() for k, v in (frappe.parse_json(reasons) or {}).items()}
	checks = run_checks(company, start)
	missing = [c["label"] for c in checks if c["status"] == RED and not reasons.get(c["key"])]
	if missing:
		frappe.throw(
			_("Give the reason for each check still red: {0}").format(", ".join(missing)),
			frappe.MandatoryError,
		)
	period = _lock(company, start, end)
	name = _record(company, start)
	doc = frappe.get_doc(CLOSE, name) if name else frappe.new_doc(CLOSE)
	doc.update(
		{
			"company": company,
			"month": start,
			"status": CLOSED,
			"accounting_period": period,
			"closed_by": frappe.session.user,
			"closed_on": now_datetime(),
		}
	)
	doc.set(
		"checks",
		[
			{
				"key": c["key"],
				"label": c["label"],
				"status": c["status"],
				"count": cint(c["count"]),
				"details": c["details"],
				"override_reason": reasons.get(c["key"]) if c["status"] == RED else None,
			}
			for c in checks
		],
	)
	doc.flags.ignore_permissions = True
	doc.save()
	audit("Month closed", CLOSE, doc.name, company=company, month=str(start), reasons=reasons)
	return doc.name


def _lock(company: str, start, end) -> str:
	"""The month's Accounting Period, every voucher type that posts closed, no exempt role."""
	name = _period(company, start)
	if name:
		period = frappe.get_doc(PERIOD, name)
		period.disabled = 0
		period.exempted_role = None
		for row in period.closed_documents:
			row.closed = 1
	else:
		period = frappe.get_doc(
			{
				"doctype": PERIOD,
				"period_name": period_name(company, start),
				"company": company,
				"start_date": start,
				"end_date": end,
				# every voucher type that posts (ERPNext's own fill-in reads the hook's rows wrongly)
				"closed_documents": [
					{"document_type": dt, "closed": 1} for dt in frappe.get_hooks("period_closing_doctypes")
				],
			}
		)
	period.flags.ignore_permissions = True
	period.save()
	return period.name


@frappe.whitelist(methods=["POST"])
def reopen_month(month: str, reason: str, company: str | None = None) -> str:
	"""The admin reopens a closed month with a reason; the Accounting Period is turned off."""
	from smart_power.sp_core.services.audit import audit

	_check_admin()
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for reopening."), frappe.MandatoryError)
	company = _company(company)
	start, _end = _bounds(month)
	name = _record(company, start)
	if not name or not is_closed(company, start):
		frappe.throw(_("{0} is not closed.").format(start.strftime("%m-%Y")))
	period = _period(company, start)
	if period:
		frappe.db.set_value(PERIOD, period, "disabled", 1)
	doc = frappe.get_doc(CLOSE, name)
	doc.status = OPEN
	doc.append(
		"reopens", {"reopened_by": frappe.session.user, "reopened_on": now_datetime(), "reason": reason}
	)
	doc.flags.ignore_permissions = True
	doc.save()
	audit("Month reopened", CLOSE, doc.name, company=company, month=str(start), reason=reason)
	return doc.name


# --- nothing new into a closed month --------------------------------------------------------------


def guard(doc, method=None) -> None:
	"""validate of the SP records that post on their own date: not into a closed month."""
	field = GUARDED.get(doc.doctype)
	if not field or doc.docstatus != 0 or not doc.get(field):
		return
	company = doc.get("company") or frappe.db.get_value("Account", doc.get("cash_account"), "company")
	if is_closed(company, doc.get(field)):
		frappe.throw(
			_("{0} is closed: nothing can be recorded on {1}.").format(
				getdate(doc.get(field)).strftime("%m-%Y"), frappe.format(doc.get(field), "Date")
			),
			title=_("Month closed"),
		)


# --- the Finance home -------------------------------------------------------------------------------


MONTHS_BACK = 12  # sp-allow-number: the year of months the Finance home looks back over


def period_status(company: str | None = None) -> dict:
	"""For the Finance home: the last month that ended, whether it is closed, and how many ended
	months since the company's first entry (a year at most) are still open."""
	company = _company(company)
	last = add_days(get_first_day(today()), -1)
	first = frappe.get_all(
		"GL Entry",
		{"company": company, "is_cancelled": 0},
		pluck="posting_date",
		order_by="posting_date asc",
		limit=1,
	)
	first = first[0] if first else None
	open_months = 0
	for back in range(MONTHS_BACK):
		day = add_months(last, -back)
		if not first or get_last_day(day) < getdate(first):
			break
		open_months += 0 if is_closed(company, day) else 1
	return {
		"company": company,
		"month": str(get_first_day(last)),
		"closed": is_closed(company, last),
		"open_months": open_months,
	}
