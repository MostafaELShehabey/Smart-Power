"""Q3 quote request queue (SP-48): open requests, oldest first, with their quote clock.

Rows come through frappe.get_list, so each person sees only the cases SP-35 lets them see
(quote creators: their own and unclaimed requests; the admin and كاميليا: all).
"""

import frappe
from frappe import _

from smart_power.sp_sales.quote_clock import clock

CASE = "SP Case"
OPEN_STATUSES = ("Quote request", "Draft")
UNCLAIMED, MINE, ALL = "Unclaimed", "Mine", "All"
TAKE_ACTION = "Take Request"


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
	rows = frappe.get_list(
		CASE,
		filters=filters,
		fields=[
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
		],
		order_by="creation asc",
		limit_page_length=0,
	)
	types = _system_types([r.name for r in rows])
	for row in rows:
		row.update(clock(row))
		row["system_type"] = types.get(row.name)
		row.pop("creation", None)
	return rows


@frappe.whitelist(methods=["POST"])
def take(case: str) -> str:
	"""Take an unclaimed request: the workflow's Take Request (the user becomes its quote creator)."""
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc(CASE, case)
	doc.check_permission("read")
	if doc.quote_creator:
		frappe.throw(_("This request was already taken by {0}.").format(frappe.bold(doc.quote_creator)))
	return apply_workflow(doc, TAKE_ACTION).name


def _system_types(cases: list[str]) -> dict[str, str]:
	"""Each case's first system type, as its Arabic name."""
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
		first.setdefault(r.parent, labels.get(r.system_type) or r.system_type)
	return first
