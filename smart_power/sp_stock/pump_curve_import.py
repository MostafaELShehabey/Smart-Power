"""Pump curves from Excel (SP-184): one row per curve point, with Arabic headers.

The rows of a pump replace its curve. A pump with a bad row keeps the curve it has, because half
a curve would quietly change which duties it covers; every other pump in the file still imports.
A check run reports the same results and saves nothing.
"""

import math

import frappe
from frappe import _
from frappe.utils import cint, cstr
from frappe.utils.xlsxutils import build_xlsx_response, read_xlsx_file_from_attached_file

# (key, Arabic header, English header)
COLUMNS = (
	("item_code", "كود الطلمبة", "Pump Code"),
	("flow_m3h", "التصرف (م³/ساعة)", "Flow (m³/h)"),
	("head_m", "الرفع (متر)", "Head (m)"),
)
HEADER_TO_KEY = {header.strip().lower(): key for key, ar, en in COLUMNS for header in (ar, en, key)}
TEMPLATE_NAME = "sp-pump-curves-template"
OK, ERROR, SKIPPED = "OK", "Error", "Skipped"
FIRST_DATA_ROW = 2  # sp-allow-number: row 1 of the sheet is the header


@frappe.whitelist()
def get_import_template():
	"""Download the Excel template: one header row in Arabic."""
	frappe.has_permission("Item", "write", throw=True)
	build_xlsx_response([[ar for _key, ar, _en in COLUMNS]], TEMPLATE_NAME)


@frappe.whitelist(methods=["POST"])
def import_curves(file_url: str, dry_run: int = 0) -> dict:
	"""Check or import an uploaded .xlsx file. Returns counts and one result per row."""
	frappe.has_permission("Item", "write", throw=True)
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	file_doc.check_permission("read")
	rows = read_xlsx_file_from_attached_file(fcontent=file_doc.get_content()) or []
	return import_rows(rows, cint(dry_run))


def _number(value) -> float | None:
	"""A real number that is not negative, or None."""
	try:
		number = float(cstr(value).strip())
	except ValueError:
		return None
	return number if math.isfinite(number) and number >= 0 else None


def _read_row(excel_row: int, data: dict, flows: set) -> dict:
	code = cstr(data.get("item_code")).strip()
	flow, head = _number(data.get("flow_m3h")), _number(data.get("head_m"))
	result = {"row": excel_row, "item_code": code, "status": OK, "message": "", "flow": flow, "head": head}
	message = None
	if not code:
		message = _("The pump code is empty.")
	elif not frappe.db.exists("Item", code):
		message = _("Pump {0} does not exist.").format(code)
	elif flow is None or head is None:
		message = _("Flow and head must be numbers that are not negative.")
	elif flow in flows:
		message = _("Flow {0} is repeated for this pump.").format(f"{flow:g}")
	if message:
		return {**result, "status": ERROR, "message": message}
	flows.add(flow)
	return result


def _save_curve(code: str, rows: list[dict]) -> str | None:
	"""Replace a pump's curve. Returns the error, if any."""
	frappe.db.savepoint("sp_curve_import")
	try:
		doc = frappe.get_doc("Item", code)
		doc.set("sp_curve_points", [{"flow_m3h": r["flow"], "head_m": r["head"]} for r in rows])
		doc.save()
	except Exception as e:
		frappe.db.rollback(save_point="sp_curve_import")
		frappe.clear_messages()
		return cstr(e) or e.__class__.__name__
	return None


def import_rows(rows: list[list], dry_run: int = 0) -> dict:
	"""rows[0] is the header row. Spreadsheet row numbers in the results."""
	if not rows:
		frappe.throw(_("The file is empty."))
	keys = [HEADER_TO_KEY.get(cstr(h).strip().lower()) for h in rows[0]]
	if not {key for key, _ar, _en in COLUMNS} <= set(keys):
		frappe.throw(_("The file needs the columns: pump code, flow and head."))

	results, pumps, flows = [], {}, {}
	for excel_row, values in enumerate(rows[1:], start=FIRST_DATA_ROW):
		data = {k: v for k, v in zip(keys, values, strict=False) if k and cstr(v).strip() != ""}
		if not data:
			continue
		code = cstr(data.get("item_code")).strip()
		result = _read_row(excel_row, data, flows.setdefault(code, set()))
		results.append(result)
		pumps.setdefault(code, []).append(result)

	ready = 0
	for code, pump_rows in pumps.items():
		bad = next((r for r in pump_rows if r["status"] == ERROR), None)
		error = None if bad or dry_run else _save_curve(code, pump_rows)
		if bad:
			for row in pump_rows:
				if row["status"] == OK:
					row.update(
						status=SKIPPED,
						message=_("This pump keeps its curve until row {0} is fixed.").format(bad["row"]),
					)
		elif error:
			for row in pump_rows:
				row.update(status=ERROR, message=error)
		else:
			ready += 1

	return {
		"pumps": ready,
		"points": sum(r["status"] == OK for r in results),
		"errors": sum(r["status"] == ERROR for r in results),
		"skipped": sum(r["status"] == SKIPPED for r in results),
		"dry_run": cint(dry_run),
		"rows": [{k: v for k, v in r.items() if k not in ("flow", "head")} for r in results],
	}
