"""Qualification and compliance (RG1, SP-101): the EgyptERA documents with their expiry reminders,
and the semi-annual reports with the installed capacity statement (R3).

- **SP Compliance Document**: a qualification document (type, number, issue and expiry dates, file)
  and the days before expiry at which it reminds (60, 30, 7 unless changed). Its status (Valid,
  Expiring, Expired) follows the expiry date.
- **expiry_reminders** (daily): a document that has reached one of its marks alerts the compliance
  officers and the admins, once per mark. A missed day is caught up: the tightest mark reached is
  the one sent. A new expiry date starts the marks again.
- **SP Compliance Report**: a period's report (Draft, Submitted) with its file. "Generate Statement"
  opens R3 for the period; attach_statement puts the statement's Excel export on the report and
  keeps its rows as the snapshot.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, formatdate, getdate, nowdate

DOCUMENT, REPORT = "SP Compliance Document", "SP Compliance Report"
STATEMENT = "SP Installed Capacity"
EVENT = "compliance_expiry"
OFFICER, ADMIN = "SP Regulatory Compliance", "SP Admin"
DEFAULT_MARKS = "60,30,7"
VALID, EXPIRING, EXPIRED = "Valid", "Expiring", "Expired"
DRAFT, SUBMITTED = "Draft", "Submitted"
FILE_PREFIX = "installed-capacity-"


def marks_of(text: str | None) -> list[int]:
	"""The reminder days of a document, the furthest first."""
	parts = [p.strip() for p in (text or DEFAULT_MARKS).split(",") if p.strip()]
	if not parts or any(not p.isdigit() or not cint(p) for p in parts):
		frappe.throw(_("Reminder days are whole numbers of days separated by commas, such as 60,30,7."))
	return sorted({cint(p) for p in parts}, reverse=True)


def status_of(expiry_date, marks: list[int], today=None) -> str:
	if not expiry_date:
		return VALID
	left = date_diff(expiry_date, today or nowdate())
	if left < 0:
		return EXPIRED
	return EXPIRING if left <= marks[0] else VALID


def validate_document(doc) -> None:
	marks = marks_of(doc.reminder_days)
	doc.reminder_days = ",".join(str(m) for m in marks)
	if doc.issue_date and doc.expiry_date and getdate(doc.issue_date) > getdate(doc.expiry_date):
		frappe.throw(_("The issue date is after the expiry date."))
	doc.status = status_of(doc.expiry_date, marks)


def _users_with(role: str) -> list[str]:
	users = frappe.get_all("Has Role", {"role": role, "parenttype": "User"}, pluck="parent")
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")


def recipients() -> list[str]:
	return sorted({*_users_with(OFFICER), *_users_with(ADMIN)})


def expiry_reminders(today=None) -> int:
	"""Daily: each document at one of its marks alerts the officers and the admins, once per mark."""
	today = getdate(today or nowdate())
	users = recipients()
	sent = 0
	for row in frappe.get_all(
		DOCUMENT,
		{"expiry_date": ("is", "set")},
		["name", "doc_type", "number", "expiry_date", "reminder_days", "reminded_for", "status"],
	):
		marks = marks_of(row.reminder_days)
		status = status_of(row.expiry_date, marks, today)
		if status != row.status:
			frappe.db.set_value(DOCUMENT, row.name, "status", status, update_modified=False)
		left = date_diff(row.expiry_date, today)
		reached = [m for m in marks if left <= m]
		if not reached:
			continue
		key = f"{row.expiry_date}:{min(reached)}"
		if row.reminded_for == key:
			continue
		_remind(row, left, users)
		frappe.db.set_value(DOCUMENT, row.name, "reminded_for", key, update_modified=False)
		sent += 1
	return sent


def _remind(row, left: int, users: list[str]) -> None:
	from smart_power.notify import send

	def subject():  # in each reader's language (BUG-22)
		title = " ".join(p for p in (_(row.doc_type), row.number) if p)
		if left < 0:
			return _("{0} expired on {1}").format(title, formatdate(row.expiry_date))
		return _("{0} expires in {1} days, on {2}").format(title, left, formatdate(row.expiry_date))

	send(EVENT, users, DOCUMENT, row.name, subject)


def expiring_filter(today=None) -> list:
	"""The documents the home card counts: expired, or expiring within the default first mark."""
	return ["<=", str(add_days(getdate(today or nowdate()), marks_of(None)[0]))]


# --- the semi-annual report -----------------------------------------------------------------------


def validate_report(doc) -> None:
	if getdate(doc.period_from) > getdate(doc.period_to):
		frappe.throw(_("The period's start is after its end."))
	if doc.status == SUBMITTED and not doc.submitted_on:
		doc.submitted_on = nowdate()
	if doc.status == DRAFT:
		doc.submitted_on = None


@frappe.whitelist()
def attach_statement(name: str) -> dict:
	"""Put the period's installed capacity statement on the report: its Excel export as the file,
	and its rows as the snapshot."""
	from frappe.utils.xlsxutils import make_xlsx

	from smart_power.sp_stations.report.sp_installed_capacity.sp_installed_capacity import execute

	doc = frappe.get_doc(REPORT, name)
	doc.check_permission("write")
	if doc.status == SUBMITTED:
		frappe.throw(_("A submitted report keeps its statement."))
	filters = {"from_date": str(doc.period_from), "to_date": str(doc.period_to)}
	columns, rows = execute(filters)
	table = [[c["label"] for c in columns]] + [[r.get(c["fieldname"]) for c in columns] for r in rows]
	content = make_xlsx(table, _("Installed Capacity")).getvalue()
	attached = {"attached_to_doctype": REPORT, "attached_to_name": doc.name, "attached_to_field": "file"}
	# a statement attached again replaces the earlier one
	for old in frappe.get_all("File", {**attached, "file_name": ("like", f"{FILE_PREFIX}%")}, pluck="name"):
		frappe.delete_doc("File", old, ignore_permissions=True)
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{FILE_PREFIX}{doc.period_from}-{doc.period_to}.xlsx",
			**attached,
			"is_private": 1,
			"content": content,
		}
	).insert(ignore_permissions=True)
	doc.file = file.file_url
	doc.r3_snapshot = json.dumps({"filters": filters, "rows": rows}, ensure_ascii=False, default=str)
	doc.save()
	return {"file": file.file_url, "stations": rows[-1].get("count", 0) if rows else 0}
