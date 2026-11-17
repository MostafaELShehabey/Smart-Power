"""The list pattern (SP-45): saved-view tabs and a totals row on every main list.

    views_for(user)              {doctype: [tabs]} the user sees (SP List View, by role), for the boot
    totals(doctype, filters, fields)   the money columns' sums over every row the filters match

Each list also keeps Frappe's own filter panel, column picker, bulk actions (export, print,
assign) and Excel export / Data Import; this adds what Frappe has not: the tabs and the totals.
"""

import json

import frappe
from frappe.utils import flt

from smart_power.sp_core.setup.seed import defaults

VIEW = "SP List View"
MAX_ROWS = 50000  # sp-allow-number: rows summed in one totals call; a list larger than this is a report


def views_for(user: str | None = None) -> dict[str, list[dict]]:
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	out: dict[str, list[dict]] = {}
	for v in frappe.get_all(
		VIEW,
		filters={"is_active": 1},
		fields=["list_doctype", "label", "filters", "roles", "sort_order"],
		order_by="list_doctype asc, sort_order asc",
	):
		allowed = {r.strip() for r in (v.roles or "").split(",") if r.strip()}
		if allowed and user != "Administrator" and not allowed & roles:
			continue
		out.setdefault(v.list_doctype, []).append(
			{"label": v.label, "filters": json.loads(v.filters) if v.filters else []}
		)
	return out


def boot(bootinfo) -> None:
	"""boot_session: the list tabs this user sees."""
	if frappe.db.table_exists(VIEW):
		bootinfo.sp_list_views = views_for()


def seed_list_views() -> None:
	"""The seed tabs that are missing (matched by list and label)."""
	for row in defaults()["list_views"]["views"]:
		if frappe.db.exists(VIEW, {"list_doctype": row["list_doctype"], "label": row["label"]}):
			continue
		frappe.get_doc(
			{
				"doctype": VIEW,
				"list_doctype": row["list_doctype"],
				"label": row["label"],
				"sort_order": row["sort_order"],
				"filters": json.dumps(row["filters"], ensure_ascii=False),
				"roles": row.get("roles"),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)


@frappe.whitelist()
def totals(doctype: str, filters: str | list | None = None, fields: str | list | None = None) -> dict:
	"""The sums of the money columns over every row the user may see that the filters match."""
	fields = frappe.parse_json(fields) if isinstance(fields, str) else (fields or [])
	meta = frappe.get_meta(doctype)
	money = [f for f in fields if (df := meta.get_field(f)) and df.fieldtype in ("Currency", "Float")]
	if not money:
		return {}
	rows = frappe.get_list(
		doctype,
		filters=frappe.parse_json(filters) if isinstance(filters, str) else filters,
		fields=money,
		limit_page_length=MAX_ROWS,
	)
	return {f: sum(flt(r.get(f)) for r in rows) for f in money}
