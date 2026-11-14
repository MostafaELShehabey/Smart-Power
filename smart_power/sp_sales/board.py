"""F1 follow-up board (SP-66): the cases by stage, for the follow-up team.

    board(filters) -> {columns, cards, sees_all}
    move_case(case, to_column)         a drag between columns, through the case workflow
    mark_won(case, quotation)          the "mark won" dialog: the accepted option, then Won

The follow-up lead (SP Followup All), the admin and the system manager see every case; anyone
else sees the cases they follow up. A card carries what the follow-up owner needs to pick the
next call: the customer, the quote total at sale price, the last call, the next call and how
long the quote is still valid. Each card lists the columns it may move to, from the workflow's
transitions for this user, so the board refuses a drag before asking the server (which checks
again). Won and Lost open their dialogs on the board (mark_won here, mark_lost in followup).
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.model.workflow import get_workflow, get_workflow_safe_globals
from frappe.utils import add_days, get_datetime, get_fullname, getdate, now_datetime

from smart_power.permissions import _case_sees_all

CASE, CALL, TASK, QUOTE = "SP Case", "SP Call Log", "SP Task", "Quotation"
CALL_TASK, TASK_OPEN = "Follow-up Call", "Open"
WON, LOST = "Won", "Lost"
# column → the case statuses it shows; a drag lands on the first one
COLUMNS = {
	"waiting": ("Quote request", "Draft"),
	"sent": ("Sent to customer",),
	"follow_up": ("Follow-up",),
	"won": (WON,),
	"lost": (LOST,),
}


def column_labels() -> dict[str, str]:
	return {
		"waiting": _("Waiting for quote"),
		"sent": _("Sent to customer"),
		"follow_up": _("Following up"),
		"won": _("Won"),
		"lost": _("Lost"),
	}


# Won and Lost keep only their latest cases on the board; the list view has the rest
CLOSED_ON_BOARD = 50  # sp-allow-number: cards per closed column, a screen size
CARD_FIELDS = [
	"name",
	"customer",
	"customer_name",
	"mobile",
	"channel",
	"status",
	"follow_up_owner",
	"quote_creator",
	"requested_by",
	"accepted_quotation",
	"last_action_at",
	"owner",
]


def column_of(status: str) -> str | None:
	return next((key for key, statuses in COLUMNS.items() if status in statuses), None)


@frappe.whitelist()
def board(filters: str | dict | None = None) -> dict:
	"""The cards of the board, with their column and the columns they may move to."""
	frappe.has_permission(CASE, "read", throw=True)
	filters = frappe.parse_json(filters) or {}
	sees_all = _case_sees_all(frappe.session.user)
	where = _filters(filters, sees_all)
	if where is None:
		return {"columns": _columns(), "cards": [], "sees_all": sees_all}

	open_statuses = [s for key in ("waiting", "sent", "follow_up") for s in COLUMNS[key]]
	rows = frappe.get_list(
		CASE,
		filters={**where, "status": ("in", open_statuses)},
		fields=CARD_FIELDS,
		order_by="last_action_at asc",
		limit_page_length=0,
	)
	for status in (WON, LOST):
		rows += frappe.get_list(
			CASE,
			filters={**where, "status": status},
			fields=CARD_FIELDS,
			order_by="modified desc",
			limit_page_length=CLOSED_ON_BOARD,
		)
	return {"columns": _columns(), "cards": _cards(rows), "sees_all": sees_all}


def _columns() -> list[dict]:
	return [{"key": key, "label": label} for key, label in column_labels().items()]


def _filters(filters: dict, sees_all: bool) -> dict | None:
	"""Board filters as case filters; None when nothing can match."""
	where = {}
	if not sees_all:
		where["follow_up_owner"] = frappe.session.user
	elif filters.get("owner"):
		where["follow_up_owner"] = filters["owner"]
	if filters.get("channel"):
		where["channel"] = filters["channel"]
	names = None
	if filters.get("system_type"):
		names = set(
			frappe.get_all(
				"SP Case System Type",
				{"parenttype": CASE, "system_type": filters["system_type"]},
				pluck="parent",
			)
		)
	if filters.get("region"):
		customers = frappe.get_all("Customer", {"sp_region": filters["region"]}, pluck="name")
		where["customer"] = ("in", customers or [""])
	if names is not None:
		if not names:
			return None
		where["name"] = ("in", sorted(names))
	return where


def _cards(rows: list[dict]) -> list[dict]:
	if not rows:
		return []
	names = [r.name for r in rows]
	systems, quotes, calls, next_calls = (
		_systems(names),
		_quotes(rows),
		_last_calls(names),
		_next_calls(names),
	)
	transitions = _transitions()
	now = now_datetime()
	cards = []
	for row in rows:
		quote = quotes.get(row.name) or {}
		call = calls.get(row.name) or {}
		cards.append(
			{
				"name": row.name,
				"customer": row.customer,
				"customer_name": row.customer_name,
				"mobile": row.mobile,
				"channel": row.channel,
				"status": row.status,
				"column": column_of(row.status),
				"systems": systems.get(row.name, []),
				"follow_up_owner": row.follow_up_owner,
				"follow_up_owner_name": get_fullname(row.follow_up_owner) if row.follow_up_owner else None,
				"quote_creator_name": get_fullname(row.quote_creator) if row.quote_creator else None,
				"quotation": quote.get("name"),
				"total": quote.get("total"),
				"currency": quote.get("currency"),
				"last_call": call.get("label"),
				"last_call_at": call.get("call_time"),
				"next_call_at": next_calls.get(row.name) or call.get("next_call_at"),
				**_expiry(quote.get("valid_till"), row.status, now),
				"moves": _moves(row, transitions),
			}
		)
	return cards


def _systems(names: list[str]) -> dict[str, list[str]]:
	rows = frappe.get_all(
		"SP Case System Type",
		{"parenttype": CASE, "parent": ("in", names)},
		["parent", "system_type"],
		order_by="idx asc",
	)
	labels = _labels([r.system_type for r in rows])
	out = {}
	for r in rows:
		out.setdefault(r.parent, []).append(labels.get(r.system_type) or r.system_type)
	return out


def _labels(values: list[str]) -> dict[str, str]:
	if not values:
		return {}
	return dict(
		frappe.get_all(
			"SP List Value",
			{"name": ("in", list(set(values)))},
			["name", "value_ar"],
			as_list=True,
		)
	)


def _quotes(rows: list[dict]) -> dict[str, dict]:
	"""The case's quote at sale price: the accepted version, else its latest sent version."""
	quotes = frappe.get_all(
		QUOTE,
		{"sp_case": ("in", [r.name for r in rows]), "docstatus": 1},
		["name", "sp_case", "valid_till", "rounded_total", "grand_total", "currency"],
		order_by="sp_version desc, modified desc",
	)
	accepted = {r.name: r.accepted_quotation for r in rows if r.accepted_quotation}
	out = {}
	for q in quotes:
		if q.sp_case in out and accepted.get(q.sp_case) != q.name:
			continue
		out[q.sp_case] = {
			"name": q.name,
			"valid_till": q.valid_till,
			"total": q.rounded_total or q.grand_total,
			"currency": q.currency,
		}
	return out


def _last_calls(names: list[str]) -> dict[str, dict]:
	calls = frappe.get_all(
		CALL,
		{"case": ("in", names)},
		["case", "result", "call_time", "next_call_at"],
		order_by="call_time desc",
	)
	labels = _labels([c.result for c in calls])
	out = {}
	for c in calls:
		if c.case not in out:
			out[c.case] = {**c, "label": labels.get(c.result) or c.result}
	return out


def _next_calls(names: list[str]) -> dict[str, str]:
	tasks = frappe.get_all(
		TASK,
		{
			"reference_doctype": CASE,
			"reference_name": ("in", names),
			"task_type": CALL_TASK,
			"status": TASK_OPEN,
		},
		["reference_name", "due_at"],
		order_by="due_at asc",
	)
	out = {}
	for t in tasks:
		out.setdefault(t.reference_name, t.due_at)
	return out


def _expiry(valid_till, status: str, now) -> dict:
	"""How long the quote is still valid: red under a day, expired once its day is over."""
	if not valid_till or status in (WON, LOST):
		return {"expires_at": None, "expiry": None}
	expires_at = get_datetime(add_days(getdate(valid_till), 1))  # valid through its last day
	left = expires_at - now
	if left <= timedelta(0):
		state = "expired"
	elif left < timedelta(days=1):
		state = "red"
	else:
		state = "ok"
	return {"expires_at": expires_at, "expiry": state}


def _transitions() -> list:
	workflow = get_workflow(CASE)
	roles = set(frappe.get_roles())
	return [t for t in workflow.transitions if t.allowed in roles or frappe.session.user == "Administrator"]


def _moves(row, transitions: list) -> list[str]:
	"""The columns this user may move the card to (the server checks again on the move)."""
	moves = []
	for t in transitions:
		if t.state != row.status:
			continue
		if t.condition and not frappe.safe_eval(t.condition, get_workflow_safe_globals(), {"doc": row}):
			continue
		target = column_of(t.next_state)
		if target and target != column_of(row.status) and target not in moves:
			moves.append(target)
	return moves


def _transition_to(doc, to_column: str):
	"""The workflow action that takes this case into the column, for this user."""
	from frappe.model.workflow import get_transitions

	targets = COLUMNS.get(to_column)
	if not targets:
		frappe.throw(_("Unknown column {0}.").format(frappe.bold(to_column)))
	for t in get_transitions(doc):
		if t.next_state in targets:
			return t
	frappe.throw(
		_("Case {0} cannot move from {1} to {2}.").format(
			doc.name, _(doc.status), column_labels()[to_column]
		),
		frappe.ValidationError,
	)


@frappe.whitelist(methods=["POST"])
def move_case(case: str, to_column: str) -> str:
	"""A drag on the board: only the workflow's moves; Won and Lost go through their dialogs."""
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc(CASE, case)
	doc.check_permission("write")
	transition = _transition_to(doc, to_column)
	if transition.next_state in (WON, LOST):
		frappe.throw(_("Use the {0} dialog to close a case.").format(_(transition.next_state)))
	return apply_workflow(doc, transition.action).status


@frappe.whitelist(methods=["POST"])
def mark_won(case: str, quotation: str) -> str:
	"""The "mark won" dialog: the option the customer took becomes the approved version, then Won."""
	from frappe.model.workflow import apply_workflow

	from smart_power.sp_sales.quotation import approve_version

	doc = frappe.get_doc(CASE, case)
	doc.check_permission("write")
	transition = _transition_to(doc, "won")  # refused before anything changes
	if frappe.db.get_value(QUOTE, quotation, "sp_case") != case:
		frappe.throw(_("Quote {0} is not on case {1}.").format(quotation, case))
	if not frappe.db.get_value(QUOTE, quotation, "sp_is_approved"):
		approve_version(quotation)
	return apply_workflow(frappe.get_doc(CASE, case), transition.action).status


@frappe.whitelist()
def won_options(case: str) -> list[dict]:
	"""The sent quote versions the "mark won" dialog offers (sale prices only)."""
	frappe.get_doc(CASE, case).check_permission("read")
	quotes = frappe.get_all(
		QUOTE,
		{"sp_case": case, "docstatus": 1},
		[
			"name",
			"sp_option_label",
			"sp_version",
			"sp_is_approved",
			"rounded_total",
			"grand_total",
			"currency",
		],
		order_by="sp_option_label asc, sp_version desc",
	)
	for q in quotes:
		q.total = q.rounded_total or q.grand_total
		del q["rounded_total"], q["grand_total"]
	return quotes


def publish_update(doc, method=None) -> None:
	"""Boards refresh when a case changes (after the save commits)."""
	frappe.publish_realtime(
		"sp_case_update", {"case": doc.name, "status": doc.status}, doctype=CASE, after_commit=True
	)
