"""Import leads (SP-51, C3b): an Excel or CSV file becomes the marketing agent's leads.

    read_columns(file_url)                 the file's columns and a guessed mapping
    dry_run(file_url, mapping, campaign)   {new, duplicates, errors}; nothing is saved
    start(file_url, mapping, campaign)     an SP Lead Import, run as a background job (queue long):
                                           each new row becomes her lead, tagged with the campaign;
                                           a result file (one line per row) is attached to it

A duplicate is a mobile that is already a customer or a lead, or repeats in the file. The rules of
one lead are the Lead's own (smart_power.sp_sales.leads), so a row that would fail on its own is
an error here, with its reason.
"""

import csv
import io
import json

import frappe
from frappe import _
from frappe.utils import cstr
from frappe.utils.csvutils import read_csv_content
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

from smart_power.sp_sales.customer import is_valid_mobile, normalize_mobile
from smart_power.sp_sales.leads import duplicate_of

IMPORT = "SP Lead Import"
# target field → the headers it is guessed from (lower-case, Arabic and English)
FIELDS = {
	"lead_name": ("name", "lead name", "customer", "customer name", "الاسم", "اسم العميل", "العميل"),
	"sp_mobile": (
		"mobile",
		"phone",
		"mobile number",
		"phone number",
		"الموبايل",
		"رقم الموبايل",
		"التليفون",
		"الهاتف",
		"رقم",
	),
	"company_name": ("company", "organization", "الشركة", "الجهة"),
	"city": ("city", "area", "المدينة", "المنطقة"),
	"notes": ("notes", "note", "comment", "ملاحظات", "ملاحظة"),
}
REQUIRED = ("lead_name", "sp_mobile")
MAX_ROWS = 5000  # sp-allow-number: one import file; larger lists are split
SAMPLE_ROWS = 4  # sp-allow-number: the header and three rows to show
NEW, DUPLICATE, ERROR = "new", "duplicate", "error"


def _check_access(campaign: str | None) -> None:
	frappe.has_permission("Lead", "create", throw=True)
	if campaign:
		frappe.get_doc("SP Campaign", campaign).check_permission("read")


def read_rows(file_url: str) -> list[list]:
	"""Header row first. The uploader's own file, .xlsx or .csv."""
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	file_doc.check_permission("read")
	content = file_doc.get_content()
	if cstr(file_doc.file_name).lower().endswith(".csv"):
		if isinstance(content, bytes):
			content = content.decode("utf-8-sig")
		rows = read_csv_content(content)
	else:
		rows = read_xlsx_file_from_attached_file(fcontent=content) or []
	rows = [[cstr(c).strip() for c in r] for r in rows if any(cstr(c).strip() for c in r)]
	if not rows:
		frappe.throw(_("The file is empty."))
	if len(rows) - 1 > MAX_ROWS:
		frappe.throw(_("A file holds at most {0} leads; split it.").format(MAX_ROWS))
	return rows


def guess_mapping(headers: list[str]) -> dict:
	mapping = {}
	for field, names in FIELDS.items():
		for i, header in enumerate(headers):
			if header.strip().lower() in names and i not in mapping.values():
				mapping[field] = i
				break
	return mapping


@frappe.whitelist()
def read_columns(file_url: str) -> dict:
	_check_access(None)
	rows = read_rows(file_url)
	return {
		"headers": rows[0],
		"sample": rows[1:SAMPLE_ROWS],
		"rows": len(rows) - 1,
		"mapping": guess_mapping(rows[0]),
		"fields": list(FIELDS),
	}


def _mapping(mapping) -> dict:
	mapping = frappe.parse_json(mapping) if isinstance(mapping, str) else dict(mapping or {})
	mapping = {f: int(i) for f, i in mapping.items() if f in FIELDS and i not in (None, "")}
	missing = [f for f in REQUIRED if f not in mapping]
	if missing:
		frappe.throw(_("Choose the column of: {0}.").format(", ".join(_(f) for f in missing)))
	return mapping


def classify(rows: list[list], mapping: dict) -> list[dict]:
	"""One result per data row: new (with its values), duplicate (and of what) or error."""
	seen, out = {}, []
	for number, row in enumerate(rows[1:], start=2):  # sp-allow-number: spreadsheet row numbers (header = 1)
		values = {f: (row[i] if i < len(row) else "") for f, i in mapping.items()}
		mobile = normalize_mobile(values.get("sp_mobile"))
		result = {"row": number, "mobile": mobile, "name": values.get("lead_name")}
		if not values.get("lead_name"):
			out.append({**result, "status": ERROR, "message": _("No name.")})
			continue
		if not is_valid_mobile(mobile):
			out.append({**result, "status": ERROR, "message": _("Not a valid Egyptian mobile.")})
			continue
		if mobile in seen:
			out.append({**result, "status": DUPLICATE, "message": _("Repeats row {0}.").format(seen[mobile])})
			continue
		seen[mobile] = number
		duplicate = duplicate_of(mobile)
		if duplicate:
			out.append(
				{
					**result,
					"status": DUPLICATE,
					"message": _("Already {0} {1}.").format(_(duplicate[0]), duplicate[1]),
				}
			)
			continue
		out.append({**result, "status": NEW, "values": {**values, "sp_mobile": mobile}})
	return out


def summary(results: list[dict]) -> dict:
	return {
		"new": sum(1 for r in results if r["status"] == NEW),
		"duplicates": [r for r in results if r["status"] == DUPLICATE],
		"errors": [r for r in results if r["status"] == ERROR],
	}


@frappe.whitelist()
def dry_run(file_url: str, mapping: dict | str, campaign: str | None = None) -> dict:
	_check_access(campaign)
	result = summary(classify(read_rows(file_url), _mapping(mapping)))
	return {**result, "duplicate_count": len(result["duplicates"]), "error_count": len(result["errors"])}


@frappe.whitelist(methods=["POST"])
def start(file_url: str, mapping: dict | str, campaign: str | None = None) -> str:
	"""Queue the import; the page follows its SP Lead Import."""
	_check_access(campaign)
	mapping = _mapping(mapping)
	read_rows(file_url)  # a bad file fails now, not in the background
	doc = frappe.get_doc(
		{
			"doctype": IMPORT,
			"import_file": file_url,
			"campaign": campaign,
			"mapping": json.dumps(mapping),
			"status": "Queued",
		}
	).insert()
	frappe.enqueue(
		"smart_power.sp_sales.lead_import.run",
		queue="long",
		import_name=doc.name,
		enqueue_after_commit=True,
		now=frappe.flags.in_test,
	)
	return doc.name


def run(import_name: str) -> None:
	"""The background job: her leads, as her (a job runs as the user who queued it, so the leads
	are hers), tagged with the campaign."""
	doc = frappe.get_doc(IMPORT, import_name)
	doc.db_set("status", "Running")
	try:
		results = classify(read_rows(doc.import_file), json.loads(doc.mapping))
		for r in results:
			if r["status"] != NEW:
				continue
			try:
				lead = frappe.get_doc({"doctype": "Lead", **r["values"], "sp_campaign": doc.campaign or None})
				lead.insert()
				r["lead"] = lead.name
			except Exception as e:
				r.update(status=ERROR, message=cstr(e))
				frappe.clear_messages()
		counts = summary(results)
		doc.db_set(
			{
				"status": "Done",
				"new_count": counts["new"],
				"duplicate_count": len(counts["duplicates"]),
				"error_count": len(counts["errors"]),
				"result_file": _result_file(doc, results),
			}
		)
	except Exception as e:
		frappe.db.rollback()
		frappe.get_doc(IMPORT, import_name).db_set({"status": "Failed", "error": cstr(e)})
		frappe.log_error(title=f"Lead import {import_name} failed")


def _result_file(doc, results: list[dict]) -> str:
	out = io.StringIO()
	writer = csv.writer(out)
	writer.writerow([_("Row"), _("Name"), _("Mobile"), _("Result"), _("Lead"), _("Reason")])
	labels = {NEW: _("Created"), DUPLICATE: _("Duplicate"), ERROR: _("Error")}
	for r in results:
		writer.writerow(
			[
				r["row"],
				r.get("name"),
				r.get("mobile"),
				labels[r["status"]],
				r.get("lead", ""),
				r.get("message", ""),
			]
		)
	f = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{doc.name}-result.csv",
			"content": "﻿" + out.getvalue(),  # Excel opens Arabic UTF-8 with the BOM
			"attached_to_doctype": IMPORT,
			"attached_to_name": doc.name,
			"is_private": 1,
		}
	).insert(ignore_permissions=True)
	return f.file_url
