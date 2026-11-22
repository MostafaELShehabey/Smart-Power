"""R6 Conversion (SP-144): where do sales leak, by channel and by person?

The period is the request's: a case counts in the period its request came in (SP Case creation),
and what became of it is followed to today.

    requests     the cases opened in the period
    quoted       of them, those whose quote was sent to the customer (quote_sent_at)
    won          of them, those won
    win rate     won / quoted (the story's 9 of 30 = 30%)
    hours        the average hours from the request to the quote sent
    in 24 h      the share of requests quoted by their 24-hour deadline (quote_due_at, SP-48)

Group by channel, requester, quote creator or follow-up owner; or by lost reason, for the lost
cases of the period ("price check only" among them). Filter by system type and region.

    rows(filters)    the report rows, the total last
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, get_datetime, get_first_day, get_last_day, getdate, today

CASE = "SP Case"
WON, LOST = "Won", "Lost"
CHANNEL, REQUESTER, CREATOR, OWNER, REASON = (
	"Channel",
	"Requester",
	"Quote creator",
	"Follow-up owner",
	"Lost reason",
)
GROUP_FIELDS = {
	CHANNEL: "channel",
	REQUESTER: "requested_by",
	CREATOR: "quote_creator",
	OWNER: "follow_up_owner",
}
PERCENT = 100  # sp-allow-number: a share as a percentage
SLA_HOURS = 24  # sp-allow-number: the story's 24 h, when a case has no deadline stored
SECONDS_PER_HOUR = 3600  # sp-allow-number: seconds in an hour
DIGITS = 1  # sp-allow-number: rates and hours to one decimal


def _filters(filters) -> frappe._dict:
	filters = frappe._dict(filters or {})
	filters.from_date = getdate(filters.get("from_date") or get_first_day(today()))
	filters.to_date = getdate(filters.get("to_date") or get_last_day(today()))
	if filters.from_date > filters.to_date:
		frappe.throw(_("The from date is after the to date."))
	filters.group_by = filters.get("group_by") or CHANNEL
	if filters.group_by not in (*GROUP_FIELDS, REASON):
		frappe.throw(_("Group by channel, a person or the lost reason."))
	return filters


def cases(filters) -> list:
	"""The period's cases, narrowed by system type and region."""
	conditions = {
		"creation": ("between", [f"{filters.from_date} 00:00:00", f"{filters.to_date} 23:59:59"]),
	}
	fields = ["name", "creation", "status", "channel", "requested_by", "quote_creator", "follow_up_owner"]
	fields += ["quote_sent_at", "quote_due_at", "lost_reason", "customer"]
	rows = frappe.get_all(CASE, conditions, fields)
	if filters.get("system_type"):
		with_type = set(
			frappe.get_all(
				"SP Case System Type",
				{"parenttype": CASE, "system_type": filters.system_type},
				pluck="parent",
			)
		)
		rows = [r for r in rows if r.name in with_type]
	if filters.get("region"):
		customers = {r.customer for r in rows if r.customer}
		in_region = set(
			frappe.get_all(
				"Customer",
				{"name": ("in", list(customers) or [""]), "sp_region": filters.region},
				pluck="name",
			)
		)
		rows = [r for r in rows if r.customer in in_region]
	return rows


def _hours(case) -> float | None:
	if not case.quote_sent_at:
		return None
	return (get_datetime(case.quote_sent_at) - get_datetime(case.creation)).total_seconds() / SECONDS_PER_HOUR


def _in_time(case) -> bool:
	if not case.quote_sent_at:
		return False
	deadline = (
		get_datetime(case.quote_due_at) if case.quote_due_at else add_to_date(case.creation, hours=SLA_HOURS)
	)
	return get_datetime(case.quote_sent_at) <= deadline


def _labels(group_by: str, keys: set) -> dict:
	keys = {k for k in keys if k}
	if group_by == CHANNEL:
		return {k: _(k) for k in keys}
	if group_by == REASON:
		arabic = (frappe.local.lang or "").startswith("ar")
		rows = frappe.get_all(
			"SP List Value", {"name": ("in", list(keys) or [""])}, ["name", "value_ar", "value_en"]
		)
		return {r.name: (r.value_ar if arabic else r.value_en) or r.value_ar or r.name for r in rows}
	return {k: frappe.utils.get_fullname(k) for k in keys}


def _funnel_row(label: str, key, group: list) -> dict:
	quoted = [c for c in group if c.quote_sent_at]
	won = [c for c in group if c.status == WON]
	hours = [h for h in (_hours(c) for c in quoted) if h is not None]
	requests = len(group)
	return {
		"group": label,
		"key": key,
		"requests": requests,
		"quoted": len(quoted),
		"won": len(won),
		"lost": len([c for c in group if c.status == LOST]),
		"win_rate": flt(len(won) * PERCENT / len(quoted), DIGITS) if quoted else 0.0,
		"quote_rate": flt(len(quoted) * PERCENT / requests, DIGITS) if requests else 0.0,
		"avg_hours": flt(sum(hours) / len(hours), DIGITS) if hours else None,
		"in_24h": flt(len([c for c in group if _in_time(c)]) * PERCENT / requests, DIGITS)
		if requests
		else 0.0,
	}


def rows(filters=None) -> list[dict]:
	filters = _filters(filters)
	found = cases(filters)
	if filters.group_by == REASON:
		lost = [c for c in found if c.status == LOST]
		groups: dict = {}
		for c in lost:
			groups.setdefault(c.lost_reason, []).append(c)
		labels = _labels(REASON, set(groups))
		out = [
			{
				"group": labels.get(key) or _("No reason"),
				"key": key,
				"lost": len(group),
				"share": flt(len(group) * PERCENT / len(lost), DIGITS),
			}
			for key, group in sorted(groups.items(), key=lambda kv: -len(kv[1]))
		]
		out.append(
			{
				"group": _("Total"),
				"key": None,
				"lost": len(lost),
				"share": PERCENT if lost else 0,
				"is_total": 1,
			}
		)
		return out
	field = GROUP_FIELDS[filters.group_by]
	groups = {}
	for c in found:
		groups.setdefault(c.get(field), []).append(c)
	labels = _labels(filters.group_by, set(groups))
	out = [
		_funnel_row(labels.get(key) or _("Not set"), key, group)
		for key, group in sorted(groups.items(), key=lambda kv: -len(kv[1]))
	]
	total = _funnel_row(_("Total"), None, found)
	total["is_total"] = 1
	return [*out, total]


def chart(data: list[dict], group_by: str | None) -> dict | None:
	total = next((r for r in data if r.get("is_total")), None)
	if not total or (group_by or CHANNEL) == REASON:
		return None
	return {
		"data": {
			"labels": [_("Requests"), _("Quoted"), _("Won")],
			"datasets": [{"name": _("Cases"), "values": [total["requests"], total["quoted"], total["won"]]}],
		},
		"type": "bar",
	}
