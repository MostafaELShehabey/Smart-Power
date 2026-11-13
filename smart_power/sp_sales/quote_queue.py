"""Q3 quote request queue (SP-48): open requests, oldest first, with their quote clock.

Every quote creator sees every open request here, so nobody takes one already taken: a
taken request shows who took it, and Take is off (SP-48). Outside the queue the SP-35 case
rule still applies, so the case itself opens only for its owners, the admin and كاميليا.
Anyone else gets the rows the case rule lets them see.
"""

import frappe
from frappe import _
from frappe.utils import get_fullname

from smart_power.sp_sales.quote_clock import clock
from smart_power.sp_sales.quote_request import QUOTE_CREATOR_ROLE, summarize_request

CASE = "SP Case"
OPEN_STATUSES = ("Quote request", "Draft")
UNCLAIMED, MINE, ALL = "Unclaimed", "Mine", "All"
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
	is_creator = QUOTE_CREATOR_ROLE in frappe.get_roles()
	# quote creators see the whole queue; everyone else what the case rule allows
	lister = frappe.get_all if is_creator else frappe.get_list
	rows = lister(CASE, filters=filters, fields=QUEUE_FIELDS, order_by="creation asc", limit_page_length=0)
	names = [r.name for r in rows]
	types, loads = _system_types(names), _load_counts(names)
	for row in rows:
		row.update(clock(row))
		code, row["system_type"] = types.get(row.name, (None, None))
		row.update(summarize_request(code, row.pop("request_details", None), loads.get(row.name, 0)))
		row["follow_up_owner_name"] = row.follow_up_owner and get_fullname(row.follow_up_owner)
		row["requested_by_name"] = row.requested_by and get_fullname(row.requested_by)
		row["can_take"] = is_creator and not row.quote_creator and row.status == OPEN_STATUSES[0]
		row["taken_by"] = row.quote_creator and get_fullname(row.quote_creator)
		row["can_open"] = frappe.has_permission(CASE, "read", doc=row.name)
		row.pop("creation", None)
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
