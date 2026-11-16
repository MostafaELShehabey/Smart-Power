"""Global search (SP-41, G5): one box for a customer or mobile, a station, a request or quote, a
purchase order, an item code or a cheque number.

Each kind is searched with the user's own permissions (frappe.get_list applies the row rules of
SP-35), so a record the user may not see never comes back. On top of that, a colleague's
customer (someone else follows it up and it is not featured, SP-47) is left out, and so are its
requests: only its owner and the admin find it. Arabic is matched in one spelling (search_key),
at most five results a kind with a "show all" to the filtered list, exact matches first.

    global_search(q)
"""

from dataclasses import dataclass

import frappe
from frappe import _

from smart_power.sp_core.search_key import normalize
from smart_power.sp_sales.customer import is_valid_mobile, normalize_mobile

PER_KIND = 5  # sp-allow-number: the story's five results a kind
MIN_LENGTH = 2  # sp-allow-number: shorter text finds too much to help
OVERFETCH = 3  # sp-allow-number: fetch more, as a colleague's customers are left out after


@dataclass(frozen=True)
class Kind:
	doctype: str
	label: str
	fields: tuple[str, ...]  # name, title, subtitle
	match: tuple[str, ...]  # fields searched with the text as typed
	keyed: tuple[str, ...] = ()  # fields searched in the one spelling (search_key)
	mobile: tuple[str, ...] = ()  # fields searched with a mobile in its local form
	exact: tuple[str, ...] = ("name",)  # fields whose exact match ranks first


KINDS = (
	Kind("SP Station", "Stations", ("name", "customer_name", "status"), ("name",)),
	Kind(
		"Customer",
		"Customers",
		("name", "customer_name", "sp_mobile"),
		("name",),
		keyed=("sp_search_key",),
		mobile=("sp_mobile", "sp_mobile_2"),
		exact=("name", "sp_mobile"),
	),
	Kind(
		"SP Case",
		"Requests",
		("name", "customer_name", "status"),
		("name", "customer_name"),
		mobile=("mobile",),
		exact=("name", "mobile"),
	),
	Kind("Quotation", "Quotes", ("name", "customer_name", "status"), ("name", "customer_name")),
	Kind("Purchase Order", "Purchase Orders", ("name", "supplier_name", "status"), ("name", "supplier_name")),
	Kind(
		"Item",
		"Items",
		("name", "item_name", "item_group"),
		("item_code",),
		keyed=("sp_search_key",),
		exact=("name", "item_code"),
	),
	Kind(
		"SP Cheque",
		"Cheques",
		("name", "cheque_no", "customer_name"),
		("cheque_no", "name"),
		exact=("cheque_no", "name"),
	),
)


@frappe.whitelist()
def global_search(q: str) -> dict:
	"""Grouped results for one search text, the kinds with an exact match first."""
	q = (q or "").strip()
	if len(q) < MIN_LENGTH:
		return {"q": q, "groups": []}
	keyed = normalize(q)
	mobile = normalize_mobile(q) if is_valid_mobile(normalize_mobile(q)) else None
	groups = []
	for kind in KINDS:
		if not frappe.db.exists("DocType", kind.doctype) or not frappe.has_permission(kind.doctype, "read"):
			continue
		rows = _search(kind, q, keyed, mobile)
		if rows:
			groups.append(rows)
	groups.sort(key=lambda g: not g["exact"])  # stable: the kinds keep their order otherwise
	return {"q": q, "groups": groups}


def _search(kind: Kind, q: str, keyed: str, mobile: str | None) -> dict | None:
	or_filters = [[f, "like", f"%{q}%"] for f in kind.match]
	or_filters += [[f, "like", f"%{keyed}%"] for f in kind.keyed]
	if mobile:
		or_filters += [[f, "like", f"%{mobile}%"] for f in kind.mobile]
	meta = frappe.get_meta(kind.doctype)
	fields = [f for f in {*kind.fields, *kind.exact, "customer"} if f == "name" or meta.has_field(f)]
	rows = frappe.get_list(
		kind.doctype,
		or_filters=or_filters,
		fields=fields,
		order_by="modified desc",
		limit_page_length=PER_KIND * OVERFETCH,  # some may be a colleague's
	)
	rows = [r for r in rows if not _a_colleagues(kind.doctype, r)]
	if not rows:
		return None
	wanted = {q.casefold(), (mobile or "").casefold()} - {""}

	def is_exact(row) -> bool:
		return any(str(row.get(f) or "").casefold() in wanted for f in kind.exact)

	rows.sort(key=lambda r: not is_exact(r))
	_name, title, subtitle = kind.fields
	more_field, more_text = (kind.keyed[0], keyed) if kind.keyed else (kind.match[0], q)
	return {
		"doctype": kind.doctype,
		"label": _(kind.label),
		"exact": any(is_exact(r) for r in rows),
		"results": [
			{
				"name": r.name,
				"title": r.get(title) or r.name,
				"subtitle": " · ".join(str(v) for v in (r.name, _(r.get(subtitle) or "")) if v),
				"route": ["Form", kind.doctype, r.name],
			}
			for r in rows[:PER_KIND]
		],
		"more": {"route": ["List", kind.doctype], "route_options": {more_field: ["like", f"%{more_text}%"]}},
	}


def _a_colleagues(doctype: str, row) -> bool:
	"""A colleague's customer (or a request for one): only its owner and the admin find it."""
	from smart_power.sp_sales.quote_request import COLLEAGUE, customer_status

	customer = row.name if doctype == "Customer" else row.get("customer") if doctype == "SP Case" else None
	if not customer:
		return False
	return customer_status(customer)[0] == COLLEAGUE
