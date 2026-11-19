"""RV1 field review (SP-110): the projects manager goes through the operators' entries with flags.

Every save works out the entry's flags and keeps them on the entry (review_flags); a daily job and
every money received on a job work them out again, since a balance or held cash changes later.

    missing          a detail the operator left out (MISSING)
    amount_differs   the job's agreed amount is not the booking's
    unpaid           an outside job with money still open
    late             entered more than a day after the work date
    unusual_expense  the rule field_expense_unusual: the type's average times 1.5, or a threshold
    cash_held        the cash this entry received is still held past its limit (SP-116)

Each review action is an SP Field Review row:

    complete(name, values, reason)       fill in what is missing, with a reason (RV2 Edits)
    mark_reviewed(names, note)           one or many entries, a whole day at once
    flag_abnormal(name, note)            to the admin's RV2 Abnormal flags, with the note
    reopen_day(vehicle, work_date, why)  a locked day: reopened at once by the projects manager

The page is sp-winch-review (sp-field-review is the SP Field Review list); the phone's M12 comes with the mobile app (E16).
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cstr, date_diff, flt, get_fullname, getdate, now_datetime, nowdate

from smart_power.notify import send
from smart_power.rules import OFF, effective_level, evaluate, get_rule_setting, registry
from smart_power.rules.finance import RULE_KEY as CASH_HELD_RULE
from smart_power.rules.winch import REVIEW_EVENT
from smart_power.sp_core.review_centre import raise_item
from smart_power.sp_core.services.review import open_review_item
from smart_power.sp_winch import field_lock
from smart_power.sp_winch.bookings import BOOKING, FOR_OUTSIDE, _job_label
from smart_power.sp_winch.field_entry import (
	CASH,
	ENTERED_FIELDS,
	ENTRY,
	EXPENSE,
	JOB,
	MONEY,
	RECEIVED,
	_code,
	_collected_later,
	_has_role,
	_holder,
)

REVIEW = "SP Field Review"
LOGGED, LOCKED, REVIEWED, FLAGGED = "Logged", "Locked", "Reviewed", "Flagged"
COMPLETED, ABNORMAL, REOPENED = "Completed", "Abnormal", "Reopened"
REVIEWERS = ("SP Project Manager", "SP Winch Reviewer", "SP Admin", "System Manager")
ADMIN_ROLE, EVENT_ABNORMAL = "SP Admin", "abnormal_flag"
MISSING, AMOUNT_DIFFERS, UNPAID, LATE, UNUSUAL, CASH_HELD = (
	"missing",
	"amount_differs",
	"unpaid",
	"late",
	"unusual_expense",
	"cash_held",
)
FLAGS = (MISSING, AMOUNT_DIFFERS, UNPAID, LATE, UNUSUAL, CASH_HELD)
# what the operator may leave out when logging, and the reviewer completes
MISSING_FIELDS = {
	JOB: {"place": "Place", "agreed_amount": "Agreed Amount"},
	EXPENSE: {"photo": "Photo"},
	MONEY: {},
}
# what a reviewer may complete: what the operator entered, apart from what identifies the entry
COMPLETABLE = tuple(f for f in ENTERED_FIELDS if f not in ("entry_kind", "client_uuid", "device_time"))
LATE_DAYS = 1  # sp-allow-number: entered more than a day after the work date (the story)
DAYS_SHOWN = 7  # sp-allow-number: the page opens on the last week
REFRESH_DAYS = 60  # sp-allow-number: the daily job works out again the entries of the last two months
PAGE_SIZE = 500  # sp-allow-number: entries listed at once, a screen size
PENNY = 0.005  # sp-allow-number: half a piastre, rounding


def flag_labels() -> dict[str, str]:
	return {
		MISSING: _("Missing details"),
		AMOUNT_DIFFERS: _("Amount differs from the booking"),
		UNPAID: _("Unpaid"),
		LATE: _("Entered late"),
		UNUSUAL: _("Unusual expense"),
		CASH_HELD: _("Cash held too long"),
	}


def _money(value: float) -> str:
	return frappe.format(flt(value), "Currency")


# --- the flags -------------------------------------------------------------------------------------


def compute_flags(doc) -> list[dict]:
	"""The entry's flags, each {flag, values}: the values, not words, so that each reader sees the
	detail in their own language (detail)."""
	flags = []

	def add(flag: str, **values) -> None:
		flags.append({"flag": flag, "values": values})

	left_out = [field for field in MISSING_FIELDS.get(doc.entry_kind, {}) if not doc.get(field)]
	if left_out:
		add(MISSING, fields=left_out)
	if doc.entry_kind == JOB and doc.booking:
		booked = flt(frappe.db.get_value(BOOKING, doc.booking, "agreed_amount"))
		if abs(flt(doc.agreed_amount) - booked) > PENNY:
			add(AMOUNT_DIFFERS, agreed=flt(doc.agreed_amount), booked=booked)
	if doc.entry_kind == JOB and doc.for_kind == FOR_OUTSIDE:
		still_open = flt(doc.agreed_amount) - flt(doc.received_now) - _collected_later(doc.name)
		if still_open > PENNY:
			add(UNPAID, amount=still_open)
	if doc.entry_time and doc.work_date:
		days = date_diff(getdate(doc.entry_time), doc.work_date)
		if days > LATE_DAYS:
			add(LATE, days=days)
	for hit in evaluate(doc, REVIEW_EVENT):
		add(UNUSUAL, **hit.finding.data)
	held = _cash_held(doc)
	if held:
		add(CASH_HELD, **held)
	return flags


def detail(flag: dict) -> str:
	"""A flag's detail, in the reader's language."""
	v, kind = flag.get("values") or {}, flag.get("flag")
	if kind == MISSING:
		labels = {name: label for fields in MISSING_FIELDS.values() for name, label in fields.items()}
		return ", ".join(_(labels.get(name, name)) for name in v.get("fields", []))
	if kind == AMOUNT_DIFFERS:
		return _("{0}, booked {1}").format(_money(v.get("agreed")), _money(v.get("booked")))
	if kind == UNPAID:
		return _("{0} still open").format(_money(v.get("amount")))
	if kind == LATE:
		return _("{0} days after the work date").format(v.get("days"))
	if kind == UNUSUAL and v.get("threshold"):
		return _("Above the {0} threshold").format(_money(v["threshold"]))
	if kind == UNUSUAL:
		return _("Above {0} times the average {1}").format(v.get("factor"), _money(v.get("average")))
	if kind == CASH_HELD:
		return _("Held {0} days (limit {1})").format(v.get("days"), v.get("limit"))
	return ""


def _cash_held(doc) -> dict | None:
	"""The cash this entry received is part of what its holder still holds past the limit."""
	from smart_power.sp_finance.accounts import TRANSIT
	from smart_power.sp_finance.transit import days_held, limit_days, oldest_open_date

	if doc.entry_kind == JOB:
		cash = flt(doc.received_now)
	elif doc.entry_kind == MONEY and doc.money_kind == RECEIVED:
		cash = flt(doc.amount)
	else:
		return None
	if not cash or _code(doc.received_method) != CASH:
		return None
	spec = registry().get(CASH_HELD_RULE)
	if spec and effective_level(spec, get_rule_setting(CASH_HELD_RULE)) == OFF:
		return None
	account = frappe.db.get_value(
		"Account",
		{"company": doc.company, "sp_holder": _holder(doc), "sp_account_kind": TRANSIT, "is_group": 0},
	)
	oldest = account and oldest_open_date(account)
	if not oldest or oldest > getdate(doc.work_date):
		return None  # deposited since: what is held now came in after this entry
	held, limit = days_held(account), limit_days(account)
	if not limit or held <= limit:
		return None
	return {"days": held, "limit": limit}


def flags_of(doc_or_row) -> list[dict]:
	raw = doc_or_row.get("review_flags")
	if not raw:
		return []
	return json.loads(raw) if isinstance(raw, str) else list(raw)


def _dump(flags: list[dict]) -> str | None:
	return json.dumps(flags, ensure_ascii=False) if flags else None


def before_save(doc) -> None:
	"""The flags are kept with the entry; a reviewed entry the operator changes is reviewed again."""
	doc.review_flags = _dump(compute_flags(doc))
	if doc.is_new() or doc.status != REVIEWED or doc.flags.sp_review:
		return
	before = doc.get_doc_before_save()
	if before and any(cstr(before.get(f)) != cstr(doc.get(f)) for f in COMPLETABLE):
		doc.status = LOGGED


def on_update(doc) -> None:
	"""The cash is posted after the flags are worked out, and money received on a job changes
	what is still open on it."""
	if flt(doc.received_now) or doc.money_kind == RECEIVED:
		refresh(doc.name)
	if doc.entry_kind != MONEY:
		return
	before = doc.get_doc_before_save()
	for job in {doc.related_job, before and before.related_job}:
		if job:
			refresh(job)


def refresh(name: str) -> None:
	doc = frappe.get_doc(ENTRY, name)
	flags = _dump(compute_flags(doc))
	if flags != doc.review_flags:
		doc.db_set("review_flags", flags, update_modified=False)


def refresh_flags() -> int:
	"""Daily: balances and held cash change after the save, so the recent entries are worked out again."""
	names = frappe.get_all(
		ENTRY,
		{"status": ("!=", REVIEWED), "work_date": (">=", add_days(nowdate(), -REFRESH_DAYS))},
		pluck="name",
	)
	for name in names:
		refresh(name)
	return len(names)


# --- the actions -------------------------------------------------------------------------------------


def _check_reviewer() -> None:
	if not _has_role(REVIEWERS):
		frappe.throw(_("Only the field reviewer reviews field entries."), frappe.PermissionError)


def _reason(text: str | None, message: str) -> str:
	text = (text or "").strip()
	if not text:
		frappe.throw(message, frappe.MandatoryError)
	return text


def _log(entry, action: str, note: str | None = None, flags: list | None = None, **links) -> str:
	"""`flags`: what the entry was flagged with when the reviewer acted, if it has changed since."""
	return (
		frappe.get_doc(
			{
				"doctype": REVIEW,
				"field_entry": entry.name,
				"action": action,
				"flag": ", ".join(f["flag"] for f in (flags_of(entry) if flags is None else flags)),
				"note": note,
				"reviewed_by": frappe.session.user,
				"reviewed_at": now_datetime(),
				**links,
			}
		)
		.insert(ignore_permissions=True)  # written through these actions; the DocType has no create right
		.name
	)


@frappe.whitelist(methods=["POST"])
def complete(name: str, values: str | dict, reason: str) -> str:
	"""Fill in what the operator left out. The lock still applies: a closed day is reopened first."""
	_check_reviewer()
	reason = _reason(reason, _("Give the reason for the change."))
	values = frappe.parse_json(values) or {}
	unknown = set(values) - set(COMPLETABLE)
	if unknown:
		frappe.throw(_("{0} cannot be completed here.").format(", ".join(sorted(unknown))))
	doc = frappe.get_doc(ENTRY, name)
	changed = [f for f, v in values.items() if cstr(doc.get(f)) != cstr(v)]
	if not changed:
		frappe.throw(_("Nothing was changed."))
	before, flagged = {f: doc.get(f) for f in changed}, flags_of(doc)
	doc.update(values)
	doc.flags.sp_review = True
	doc.save()
	labels = ", ".join(_(doc.meta.get_label(f)) for f in changed)
	doc.add_comment("Info", _("Completed in review: {0}. Reason: {1}").format(labels, reason))
	item = raise_item(
		"Edit",
		doc,
		_("{0}: {1} completed in the field review ({2}). {3}").format(
			doc.name, labels, ", ".join(cstr(before[f]) or "-" for f in changed), reason
		),
	)
	_log(doc, COMPLETED, reason, flags=flagged, review_item=item.name)
	return doc.name


@frappe.whitelist(methods=["POST"])
def mark_reviewed(names: str | list, note: str | None = None) -> int:
	"""Reviewing changes nothing on the entry, so a locked day can be reviewed too."""
	_check_reviewer()
	names = frappe.parse_json(names) if isinstance(names, str) else names
	done = 0
	for name in names or []:
		doc = frappe.get_doc(ENTRY, name)
		if doc.status == REVIEWED:
			continue
		doc.db_set(
			{"status": REVIEWED, "reviewed_by": frappe.session.user, "reviewed_at": now_datetime()},
			notify=True,
		)
		_log(doc, REVIEWED, (note or "").strip() or None)
		done += 1
	return done


@frappe.whitelist(methods=["POST"])
def flag_abnormal(name: str, note: str) -> str:
	"""To the admin: listed in RV2 Abnormal flags with the note, and the admin is notified."""
	from smart_power.sp_sales.quote_request import _users_with

	_check_reviewer()
	note = _reason(note, _("Write a note for the admin."))
	doc = frappe.get_doc(ENTRY, name)
	labels = flag_labels()
	flags = ", ".join(labels.get(f["flag"], f["flag"]) for f in flags_of(doc))
	item = open_review_item(
		category="Abnormal",
		reference_doctype=ENTRY,
		reference_name=doc.name,
		summary=_("{0}: {1} on {2}{3}").format(
			doc.name,
			doc.vehicle,
			frappe.format(doc.work_date, "Date"),
			f" ({flags})" if flags else "",
		),
		amount=flt(doc.agreed_amount if doc.entry_kind == JOB else doc.amount) or None,
		highlight=True,
		reason=note,
	)
	doc.db_set("status", FLAGGED, notify=True)
	_log(doc, ABNORMAL, note, review_item=item.name)
	doc.add_comment("Info", _("Flagged abnormal: {0}").format(note))
	send(
		EVENT_ABNORMAL,
		_users_with(ADMIN_ROLE),
		ENTRY,
		doc.name,
		_("Abnormal field entry {0}: {1}").format(doc.name, note),
		from_user=frappe.session.user,
	)
	return item.name


@frappe.whitelist(methods=["POST"])
def reopen_day(vehicle: str, work_date: str, reason: str) -> dict:
	"""The projects manager or the admin reopens the day at once; any other reviewer asks them."""
	_check_reviewer()
	reason = _reason(reason, _("Give the reason for reopening the day."))
	request = field_lock.ask_to_reopen(vehicle, work_date, reason)
	if (
		_has_role(field_lock.REOPENERS)
		and frappe.db.get_value(field_lock.REQUEST, request, "status") == "Open"
	):
		field_lock.approve(request)
	for entry in frappe.get_all(ENTRY, {"vehicle": vehicle, "work_date": work_date}, pluck="name"):
		_log(frappe.get_doc(ENTRY, entry), REOPENED, reason, reopen_request=request)
	return {"request": request, "status": frappe.db.get_value(field_lock.REQUEST, request, "status")}


# --- what the page shows -------------------------------------------------------------------------


ROW_FIELDS = (
	"name",
	"entry_kind",
	"vehicle",
	"work_date",
	"status",
	"reopened",
	"logged_by",
	"on_behalf_of",
	"job_type",
	"for_kind",
	"station",
	"internal_center",
	"customer_name",
	"place",
	"agreed_amount",
	"received_now",
	"expense_type",
	"money_kind",
	"amount",
	"note",
	"photo",
	"review_flags",
	"reviewed_by",
	"entry_time",
)


def _row(r, labels: dict) -> dict:
	holder = r.on_behalf_of or r.logged_by
	if r.entry_kind == JOB:
		what, amount = _job_label(r.job_type), r.agreed_amount
		who = r.customer_name or r.station or r.internal_center or ""
	elif r.entry_kind == EXPENSE:
		what, amount, who = _job_label(r.expense_type), r.amount, ""
	else:
		what, amount, who = _(r.money_kind or MONEY), r.amount, ""
	flags = [
		{"flag": f["flag"], "label": labels.get(f["flag"], f["flag"]), "detail": detail(f)}
		for f in flags_of(r)
	]
	missing = [f for f in MISSING_FIELDS.get(r.entry_kind, {}) if not r.get(f)]
	return {
		"name": r.name,
		"entry_kind": r.entry_kind,
		"status": r.status,
		"reopened": r.reopened,
		"holder": holder,
		"holder_name": get_fullname(holder) if holder else "",
		"what": what,
		"who": who,
		"place": r.place,
		"amount": flt(amount),
		"received_now": flt(r.received_now),
		"note": r.note,
		"photo": r.photo,
		"flags": flags,
		"missing_fields": missing,
		"reviewed_by_name": get_fullname(r.reviewed_by) if r.reviewed_by else "",
	}


@frappe.whitelist()
def entries(
	from_date: str | None = None,
	to_date: str | None = None,
	vehicle: str | None = None,
	flag: str | None = None,
	to_review: int | str = 0,
) -> dict:
	"""The entries by work date and vehicle. A day or a vehicle whose entries are all reviewed is
	`reviewed` (the green check), whatever the filters leave on the screen."""
	_check_reviewer()
	to_date = getdate(to_date or nowdate())
	from_date = getdate(from_date or add_days(to_date, 1 - DAYS_SHOWN))
	filters = {"work_date": ("between", [from_date, to_date])}
	if vehicle:
		filters["vehicle"] = vehicle
	rows = frappe.get_all(
		ENTRY,
		filters=filters,
		fields=list(ROW_FIELDS),
		order_by="work_date desc, vehicle asc, creation asc",
		limit=PAGE_SIZE,
	)
	labels = flag_labels()
	counts = dict.fromkeys(FLAGS, 0)
	days: dict = {}
	for r in rows:
		row = _row(r, labels)
		for f in {f["flag"] for f in row["flags"]}:
			counts[f] = counts.get(f, 0) + 1
		day = days.setdefault(r.work_date, {"work_date": r.work_date, "reviewed": True, "vehicles": {}})
		group = day["vehicles"].setdefault(
			r.vehicle,
			{
				"vehicle": r.vehicle,
				"reviewed": True,
				"locked": field_lock.is_locked(r.vehicle, r.work_date),
				"entries": [],
			},
		)
		if r.status != REVIEWED:
			day["reviewed"] = group["reviewed"] = False
		shown = (not flag or any(f["flag"] == flag for f in row["flags"])) and not (
			int(to_review) and r.status == REVIEWED
		)
		if shown:
			group["entries"].append(row)
	out = []
	for day in days.values():
		vehicles = [v for v in day["vehicles"].values() if v["entries"]]
		if vehicles:
			out.append({**day, "vehicles": vehicles})
	return {
		"from_date": from_date,
		"to_date": to_date,
		"flags": [{"flag": f, "label": labels[f], "count": counts[f]} for f in FLAGS],
		"days": out,
		"can_reopen": _has_role(field_lock.REOPENERS),
	}


@frappe.whitelist()
def history(name: str) -> list[dict]:
	"""The review actions on one entry, newest first."""
	_check_reviewer()
	return frappe.get_all(
		REVIEW,
		{"field_entry": name},
		["action", "flag", "note", "reviewed_by", "reviewed_at"],
		order_by="creation desc",
	)
