"""Q3 quote request queue (SP-48): open requests, oldest first, with their quote clock.

Every quote creator sees every open request here, so nobody takes one already taken: a
taken request shows who took it, and Take is off (SP-48). Outside the queue the SP-35 case
rule still applies, so the case itself opens only for its owners, the admin and كاميليا.
Anyone else gets the rows the case rule lets them see.
"""

import frappe
from frappe import _
from frappe.utils import get_fullname

from smart_power.sp_sales.quote_clock import OVERDUE, amber_seconds_left, clock
from smart_power.sp_sales.quote_request import (
	ADMIN_ROLE,
	INSTALLATION_MANAGER_ROLE,
	QUOTE_CREATOR_ROLE,
	SITE_SURVEY_TASK,
	TASK_OPEN,
	_task,
	_users_with,
	summarize_request,
)

CASE = "SP Case"
OPEN_STATUSES = ("Quote request", "Draft")
UNCLAIMED, MINE, ALL, OVERDUE_VIEW = "Unclaimed", "Mine", "All", "Overdue"
TAKE_ACTION = "Take Request"
QUEUE_FIELDS = [
	"name",
	"creation",
	"quote_sent_at",
	"customer_name",
	"mobile",
	"channel",
	"status",
	"requested_by",
	"quote_creator",
	"follow_up_owner",
	"site_visit_needed",
	"quote_due_at",
	"request_details",
]


@frappe.whitelist()
def get_queue(view: str = ALL) -> list[dict]:
	"""Open requests with no quote sent yet, oldest first, for one view of the queue."""
	frappe.has_permission(CASE, "read", throw=True)
	filters = {"status": ("in", OPEN_STATUSES), "quote_sent_at": ("is", "not set")}
	if view == UNCLAIMED:
		filters["quote_creator"] = ("is", "not set")
		filters["status"] = OPEN_STATUSES[0]
	elif view == MINE:
		filters["quote_creator"] = frappe.session.user
	roles = frappe.get_roles()
	is_creator, is_admin = QUOTE_CREATOR_ROLE in roles, ADMIN_ROLE in roles
	# quote creators see the whole queue; everyone else what the case rule allows
	lister = frappe.get_all if is_creator else frappe.get_list
	rows = lister(CASE, filters=filters, fields=QUEUE_FIELDS, order_by="creation asc", limit_page_length=0)
	amber_left = amber_seconds_left()
	names = [r.name for r in rows]
	types, loads, surveys = _system_types(names), _load_counts(names), _surveys(names)
	for row in rows:
		row.update(clock(row))
		row["amber_left"] = amber_left
		code, row["system_type"] = types.get(row.name, (None, None))
		row.update(summarize_request(code, row.pop("request_details", None), loads.get(row.name, 0)))
		row["survey"] = surveys.get(row.name)  # Open or Done: the chip follows it (BUG-5)
		row["follow_up_owner_name"] = row.follow_up_owner and get_fullname(row.follow_up_owner)
		row["requested_by_name"] = row.requested_by and get_fullname(row.requested_by)
		row["can_take"] = is_creator and not row.quote_creator and row.status == OPEN_STATUSES[0]
		row["taken_by"] = row.quote_creator and get_fullname(row.quote_creator)
		row["can_open"] = frappe.has_permission(CASE, "read", doc=row.name)
		# ask for data, ask for a survey, start the quote: the request's quote creator (or anyone
		# who may take it) and the admin
		row["can_act"] = is_admin or (is_creator and row.quote_creator in (None, "", frappe.session.user))
		row.pop("creation", None)
	if view == OVERDUE_VIEW:  # past the quote clock now (AD1's "requests over 24 h", SP-138)
		rows = [row for row in rows if row["state"] == OVERDUE]
	return rows


@frappe.whitelist(methods=["POST"])
def take(case: str) -> str:
	"""Take an unclaimed request: the workflow's Take Request (the user becomes its quote creator)."""
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc(CASE, case)
	doc.check_permission("read")
	if doc.quote_creator:
		frappe.throw(
			_("This request was already taken by {0}.").format(frappe.bold(get_fullname(doc.quote_creator)))
		)
	return apply_workflow(doc, TAKE_ACTION).name


def _surveys(cases: list[str]) -> dict[str, str]:
	"""The status of each case's latest site survey (SP-95)."""
	if not cases:
		return {}
	out = {}
	for row in frappe.get_all(
		"SP Site Survey",
		filters={"case": ("in", cases)},
		fields=["case", "status"],
		order_by="creation asc",
	):
		out[row.case] = row.status  # the latest wins
	return out


def _load_counts(cases: list[str]) -> dict[str, int]:
	"""How many load lines each case has."""
	if not cases:
		return {}
	rows = frappe.get_all(
		"SP Load Line",
		filters={"parent": ("in", cases), "parenttype": CASE},
		fields=["parent", {"COUNT": "*", "as": "lines"}],
		group_by="parent",
	)
	return {r.parent: r.lines for r in rows}


def _system_types(cases: list[str]) -> dict[str, tuple[str, str]]:
	"""Each case's first system type: its name and its Arabic label."""
	if not cases:
		return {}
	rows = frappe.get_all(
		"SP Case System Type",
		filters={"parent": ("in", cases), "parenttype": CASE},
		fields=["parent", "system_type", "idx"],
		order_by="idx asc",
	)
	labels = dict(
		frappe.get_all(
			"SP List Value",
			filters={"name": ("in", list({r.system_type for r in rows}) or [""])},
			fields=["name", "value_ar"],
			as_list=True,
		)
	)
	first = {}
	for r in rows:
		first.setdefault(r.parent, (r.system_type, labels.get(r.system_type) or r.system_type))
	return first


# --- Queue actions (SP-48) ----------------------------------------------------------------------


def _check_can_act(doc) -> None:
	"""Queue actions are for quote creators (and the admin) on an open request."""
	roles = frappe.get_roles()
	if QUOTE_CREATOR_ROLE not in roles and ADMIN_ROLE not in roles:
		frappe.throw(_("Only quote creators can do this."), frappe.PermissionError)
	if doc.status not in OPEN_STATUSES:
		frappe.throw(_("Case {0} is no longer an open request.").format(doc.name))
	if doc.quote_creator and doc.quote_creator != frappe.session.user and ADMIN_ROLE not in roles:
		frappe.throw(
			_("This request was already taken by {0}.").format(frappe.bold(get_fullname(doc.quote_creator))),
			frappe.PermissionError,
		)


@frappe.whitelist(methods=["POST"])
def ask_missing_data(case: str, message: str) -> None:
	"""Ask the requester for missing data: a comment on the case and a bell alert to them."""
	from smart_power.notify import send

	doc = frappe.get_doc(CASE, case)
	_check_can_act(doc)
	message = (message or "").strip()
	if not message:
		frappe.throw(_("Write what is missing."), frappe.MandatoryError)
	doc.add_comment("Comment", message)
	if doc.requested_by and doc.requested_by != frappe.session.user:
		send(
			"missing_data",
			[doc.requested_by],
			CASE,
			doc.name,
			_("Missing data for {0}: {1}").format(doc.customer_name or doc.name, message),
			from_user=frappe.session.user,
		)


@frappe.whitelist(methods=["POST"])
def ask_site_survey(case: str) -> int:
	"""Ask installations for a site survey: an SP Site Survey (SP-95) with a task for each
	surveyor. Returns how many were asked."""
	from smart_power.sp_site import site_survey

	doc = frappe.get_doc(CASE, case)
	_check_can_act(doc)
	if site_survey.open_survey(doc.name):
		frappe.throw(_("A site survey is already asked for this request."))
	surveyors = site_survey.surveyors()
	if not surveyors:
		frappe.throw(_("No installation manager to ask."))
	site_survey.ask(doc)
	return len(surveyors)


@frappe.whitelist(methods=["POST"])
def start_quote(case: str) -> dict:
	"""Start the quote: an unclaimed request is taken first. Returns the case's open draft, or a
	new one priced from the request, for the Quote Builder (Q2, SP-57)."""
	from smart_power.sp_quotes.builder import start

	doc = frappe.get_doc(CASE, case)
	_check_can_act(doc)
	if not doc.quote_creator:
		take(doc.name)
	return start(doc.name)
