"""X13 Audit log (SP-137): who did what and when, in one list.

    rows(filters)       newest first, from:
                          SP Audit Log        confirmations, rejections, reversals, write-offs,
                                              reassignments, discounts, cancels, period close
                          SP Edit Reason Log  edits made with a reason (decision 43)
                          SP Rule Hit         rule overrides, with the reason
                          Version             field changes of the sensitive records (users and
                                              their roles, settings, rules, permissions), or of
                                              any record the filter names
                          Access Log          exports and prints of lists
                          Deleted Document    deletes
    export(filters)     the same rows, and the export itself is audited

Filters: user, doctype, name, from_date, to_date. The admin only. The log is append-only: nobody
edits or deletes an SP Audit Log row, the admin included.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

ADMIN_ROLES = ("SP Admin", "System Manager")
LIMIT = 500  # sp-allow-number: rows shown at once, a screenful of history
DEFAULT_DAYS = 30  # sp-allow-number: the last month when no date is given
DETAILS_SHOWN = 300  # sp-allow-number: characters of the details in a row
CHANGE_PARTS = 3  # sp-allow-number: a Version change is [field, old, new]
# whose field changes (Version) are sensitive enough to list without naming the record
SENSITIVE = (
	"User",
	"Role",
	"Role Profile",
	"Custom DocPerm",
	"User Permission",
	"Smart Power Settings",
	"SP Rule Setting",
	"SP Company Settings",
	"SP Document Template",
	"Accounting Period",
)


def _check_admin() -> None:
	if frappe.session.user != "Administrator" and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin reads the audit log."), frappe.PermissionError)


def _between(filters: dict) -> tuple[str, str]:
	start = getdate(filters.get("from_date") or add_days(today(), -DEFAULT_DAYS))
	end = getdate(filters.get("to_date") or today())
	return f"{start} 00:00:00", f"{end} 23:59:59"


def _where(filters: dict, at: str, user: str, doctype: str | None, name: str | None) -> dict:
	where = {at: ("between", _between(filters))}
	if filters.get("user"):
		where[user] = filters["user"]
	if filters.get("doctype") and doctype:
		where[doctype] = filters["doctype"]
	if filters.get("name") and name:
		where[name] = filters["name"]
	return where


def _short(value) -> str:
	text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
	return (text or "")[:DETAILS_SHOWN]


def _audit_rows(filters: dict) -> list[dict]:
	return [
		{
			"at": r.timestamp,
			"user": r.user,
			"action": _(r.action),
			"reference_doctype": r.reference_doctype,
			"reference_name": r.reference_name,
			"details": _short(_details(r.details)),
			"ip": r.ip,
			"source": "SP Audit Log",
		}
		for r in frappe.get_all(
			"SP Audit Log",
			filters=_where(filters, "timestamp", "user", "reference_doctype", "reference_name"),
			fields=["timestamp", "user", "action", "reference_doctype", "reference_name", "details", "ip"],
			limit=LIMIT,
			order_by="timestamp desc",
		)
	]


def _details(raw: str | None) -> str:
	try:
		data = json.loads(raw) if raw else {}
	except ValueError:
		return raw or ""
	if not isinstance(data, dict):
		return str(data)
	return " · ".join(f"{_(k.replace('_', ' ').capitalize())}: {_short(v)}" for k, v in data.items())


def _edit_rows(filters: dict) -> list[dict]:
	return [
		{
			"at": r.creation,
			"user": r.user,
			"action": _("Edited with a reason"),
			"reference_doctype": r.reference_doctype,
			"reference_name": r.reference_name,
			"details": _short(f"{r.fieldname}: {r.old_value} → {r.new_value} · {r.reason}"),
			"source": "SP Edit Reason Log",
		}
		for r in frappe.get_all(
			"SP Edit Reason Log",
			filters=_where(filters, "creation", "user", "reference_doctype", "reference_name"),
			fields=[
				"creation",
				"user",
				"reference_doctype",
				"reference_name",
				"fieldname",
				"old_value",
				"new_value",
				"reason",
			],
			limit=LIMIT,
			order_by="creation desc",
		)
	]


def _override_rows(filters: dict) -> list[dict]:
	where = _where(filters, "hit_at", "user", "reference_doctype", "reference_name")
	where["outcome"] = "Overridden"
	return [
		{
			"at": r.hit_at,
			"user": r.user,
			"action": _("Rule overridden"),
			"reference_doctype": r.reference_doctype,
			"reference_name": r.reference_name,
			"details": _short(f"{r.rule_key}: {r.message or ''} · {r.reason or ''}"),
			"source": "SP Rule Hit",
		}
		for r in frappe.get_all(
			"SP Rule Hit",
			filters=where,
			fields=["hit_at", "user", "reference_doctype", "reference_name", "rule_key", "message", "reason"],
			limit=LIMIT,
			order_by="hit_at desc",
		)
	]


def _version_rows(filters: dict) -> list[dict]:
	where = _where(filters, "creation", "owner", "ref_doctype", "docname")
	if not filters.get("name") and not filters.get("doctype"):
		where["ref_doctype"] = ("in", SENSITIVE)
	return [
		{
			"at": r.creation,
			"user": r.owner,
			"action": _("Changed"),
			"reference_doctype": r.ref_doctype,
			"reference_name": r.docname,
			"details": _short(_changes(r.data)),
			"source": "Version",
		}
		for r in frappe.get_all(
			"Version",
			filters=where,
			fields=["creation", "owner", "ref_doctype", "docname", "data"],
			limit=LIMIT,
			order_by="creation desc",
		)
	]


def _changes(raw: str | None) -> str:
	try:
		data = json.loads(raw) if raw else {}
	except ValueError:
		return ""
	parts = [f"{c[0]}: {c[1]} → {c[2]}" for c in data.get("changed") or [] if len(c) >= CHANGE_PARTS]
	for key, label in (("added", _("rows added")), ("removed", _("rows removed"))):
		if data.get(key):
			parts.append(f"{label}: {len(data[key])}")
	return " · ".join(parts)


def _access_rows(filters: dict) -> list[dict]:
	if filters.get("name"):  # an export names no single record
		return []
	return [
		{
			"at": r.creation,
			"user": r.user,
			"action": _("Exported") if r.file_type or r.method == "Export" else _(r.method or "Accessed"),
			"reference_doctype": r.export_from or r.reference_document,
			"reference_name": None,
			"details": _short(" · ".join(x for x in (r.file_type, r.report_name, r.filters) if x)),
			"source": "Access Log",
		}
		for r in frappe.get_all(
			"Access Log",
			filters=_where(filters, "creation", "user", "export_from", None),
			fields=[
				"creation",
				"user",
				"export_from",
				"reference_document",
				"file_type",
				"report_name",
				"method",
				"filters",
			],
			limit=LIMIT,
			order_by="creation desc",
		)
	]


def _delete_rows(filters: dict) -> list[dict]:
	return [
		{
			"at": r.creation,
			"user": r.owner,
			"action": _("Deleted"),
			"reference_doctype": r.deleted_doctype,
			"reference_name": r.deleted_name,
			"details": "",
			"source": "Deleted Document",
		}
		for r in frappe.get_all(
			"Deleted Document",
			filters=_where(filters, "creation", "owner", "deleted_doctype", "deleted_name"),
			fields=["creation", "owner", "deleted_doctype", "deleted_name"],
			limit=LIMIT,
			order_by="creation desc",
		)
	]


SOURCES = (_audit_rows, _edit_rows, _override_rows, _version_rows, _access_rows, _delete_rows)


@frappe.whitelist()
def rows(filters: str | dict | None = None) -> list[dict]:
	_check_admin()
	filters = frappe.parse_json(filters) or {}
	found = [row for source in SOURCES for row in source(filters)]
	found.sort(key=lambda r: str(r["at"]), reverse=True)
	return found[:LIMIT]


@frappe.whitelist(methods=["POST"])
def export(filters: str | dict | None = None) -> list[dict]:
	"""The rows to download; the export is itself audited."""
	from smart_power.sp_core.services.audit import audit

	found = rows(filters)
	audit("Audit log exported", None, None, filters=frappe.parse_json(filters) or {}, rows=len(found))
	return found
