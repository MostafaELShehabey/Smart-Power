"""C2 customer record (SP-50): everything about one customer before the call.

    customer_360(customer)   overview, requests and quotes, calls, stations, documents

Opened by whoever may read the customer (featured customers: everyone, read-only). Quotes show
their status and sale total only; stations their status and money (agreed, paid, remaining);
nothing about cost.
"""

import frappe
from frappe.utils import flt, get_fullname

CASE, QUOTE, CALL, STATION, FILE = "SP Case", "Quotation", "SP Call Log", "SP Station", "File"
CLOSED = ("Won", "Lost")
CANCELLED = 2  # sp-allow-number: docstatus


@frappe.whitelist()
def customer_360(customer: str) -> dict:
	doc = frappe.get_doc("Customer", customer)
	doc.check_permission("read")
	cases = frappe.get_all(
		CASE,
		filters={"customer": customer},
		fields=[
			"name",
			"status",
			"channel",
			"creation",
			"follow_up_owner",
			"indicative_price",
			"lost_reason",
			"modified",
		],
		order_by="creation desc",
	)
	names = [c.name for c in cases] or [""]
	system_types = {}
	for row in frappe.get_all(
		"SP Case System Type",
		{"parent": ("in", names), "parenttype": CASE},
		["parent", "system_type"],
		order_by="idx asc",
	):
		system_types.setdefault(row.parent, row.system_type)
	labels = _labels([*system_types.values(), *(c.lost_reason for c in cases)])
	for case in cases:
		case.system_type = labels.get(system_types.get(case.name)) or system_types.get(case.name)
		case.lost_reason = labels.get(case.lost_reason) or case.lost_reason
		case.follow_up_owner_name = get_fullname(case.follow_up_owner) if case.follow_up_owner else None
	quotes = frappe.get_all(
		QUOTE,
		filters={"sp_case": ("in", names), "docstatus": ("<", CANCELLED)},
		fields=[
			"name",
			"sp_case",
			"sp_option_label",
			"sp_version",
			"sp_status",
			"grand_total",
			"currency",
			"transaction_date",
			"sp_is_approved",
		],
		order_by="sp_case desc, sp_option_label asc, sp_version asc",
	)
	calls = frappe.get_all(
		CALL,
		filters={"case": ("in", names)},
		fields=["name", "case", "call_time", "result", "note", "logged_by", "next_call_at"],
		order_by="call_time desc",
	)
	call_labels = _labels([c.result for c in calls])
	for call in calls:
		call.result_label = call_labels.get(call.result) or call.result
		call.logged_by_name = get_fullname(call.logged_by) if call.logged_by else None
	stations = frappe.get_all(
		STATION,
		filters={"customer": customer},
		fields=[
			"name",
			"status",
			"agreed_amount",
			"paid_amount",
			"remaining_amount",
			"overdue_amount",
			"case",
		],
		order_by="creation desc",
	)
	active = next((c.name for c in cases if c.status not in CLOSED), None)
	return {
		"overview": {
			"customer_name": doc.customer_name,
			"mobile": doc.get("sp_mobile"),
			"mobile_2": doc.get("sp_mobile_2"),
			"tier": doc.get("sp_tier"),
			"region": _labels([doc.get("sp_region")]).get(doc.get("sp_region")) or doc.get("sp_region"),
			"featured": doc.get("sp_featured"),
			"owner_name": get_fullname(doc.sp_owner_user) if doc.get("sp_owner_user") else None,
			"open_cases": sum(1 for c in cases if c.status not in CLOSED),
			"won_cases": sum(1 for c in cases if c.status == "Won"),
			"lost_cases": sum(1 for c in cases if c.status == "Lost"),
			"agreed": sum(flt(s.agreed_amount) for s in stations),
			"paid": sum(flt(s.paid_amount) for s in stations),
			"remaining": sum(flt(s.remaining_amount) for s in stations),
			"last_call": calls[0] if calls else None,
		},
		"active_case": active,
		"can_log_call": bool(active) and frappe.has_permission(CASE, "write", active),
		"can_request": frappe.has_permission(CASE, "create"),
		"can_edit": frappe.has_permission("Customer", "write", doc),
		"cases": cases,
		"quotes": quotes,
		"calls": calls,
		"stations": stations,
		"documents": _documents(customer, names, [q.name for q in quotes], [s.name for s in stations]),
	}


def _labels(names: list) -> dict:
	"""SP List Value names → their Arabic text."""
	names = [n for n in names if n]
	if not names:
		return {}
	return dict(frappe.get_all("SP List Value", {"name": ("in", names)}, ["name", "value_ar"], as_list=True))


def _documents(customer: str, cases: list, quotes: list, stations: list) -> list:
	"""The files attached to the customer, its cases, its quotes and its stations."""
	attached = [("Customer", [customer]), (CASE, cases), (QUOTE, quotes), (STATION, stations)]
	files = []
	for doctype, names in attached:
		names = [n for n in names if n]
		if not names:
			continue
		files += frappe.get_all(
			FILE,
			filters={"attached_to_doctype": doctype, "attached_to_name": ("in", names), "is_folder": 0},
			fields=[
				"name",
				"file_name",
				"file_url",
				"attached_to_doctype",
				"attached_to_name",
				"creation",
				"is_private",
			],
		)
	return sorted(files, key=lambda f: f.creation, reverse=True)
