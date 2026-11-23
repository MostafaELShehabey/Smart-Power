"""What every migration script shares: the template, reading it, one savepoint per row, the
dry run and the CSV report."""

import csv
import io
import os

import frappe
from frappe import _
from frappe.utils import cint, cstr, now_datetime

from smart_power.sp_stock.item_codes import key, spaces

ADMIN_ROLES = ("System Manager", "SP Admin")
CREATED, UPDATED, MERGED, UNCHANGED, SKIPPED, ERROR = (
	"created",
	"updated",
	"merged",
	"unchanged",
	"skipped",
	"error",
)
ACTIONS = (CREATED, UPDATED, MERGED, UNCHANGED, SKIPPED, ERROR)
RUN_SAVEPOINT, ROW_SAVEPOINT = "sp_migration", "sp_migration_row"
YES = {"1", "yes", "y", "true", "نعم", "أيوه", "ايوه", "x", "✓"}
FIRST_DATA_ROW = 2  # sp-allow-number: the row under the header, as the workbook numbers it
REPORT_FOLDER = "migration"


def check_admin() -> None:
	frappe.only_for(ADMIN_ROLES)


def yes(value) -> bool:
	return cstr(value).strip().casefold() in YES


def template(columns: tuple, out: str) -> str:
	"""The template to fill: one sheet, the Arabic headers (English ones are read too)."""
	from openpyxl import Workbook

	check_admin()
	book = Workbook()
	book.active.append([ar for _field, ar, _en in columns])
	book.save(out)
	return out


def _workbook_rows(path: str) -> dict[str, list[list]]:
	if path.lower().endswith(".csv"):
		# the admin's own file, read by a bench script (never whitelisted)
		with open(path, encoding="utf-8-sig", newline="") as f:  # nosemgrep
			return {"": list(csv.reader(f))}
	from openpyxl import load_workbook

	book = load_workbook(path, data_only=True, read_only=True)
	return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in book.worksheets}


def read(path: str, columns: tuple, sheet: str | None = None) -> list[dict]:
	"""The rows of the first sheet (or the named one) as dicts by field, each with its row number.
	A header is matched by its Arabic or English name, ignoring spaces and case."""
	sheets = _workbook_rows(path)
	rows = sheets.get(sheet) if sheet else next(iter(sheets.values()), [])
	if not rows:
		return []
	names = {key(ar): f for f, ar, _en in columns} | {key(en): f for f, _ar, en in columns}
	header = [names.get(key(h)) for h in rows[0]]
	out = []
	for number, values in enumerate(rows[1:], start=FIRST_DATA_ROW):
		if all(cstr(v).strip() == "" for v in values):
			continue
		row = {f: (spaces(v) if isinstance(v, str) else v) for f, v in zip(header, values, strict=False) if f}
		row["_row"] = number
		out.append(row)
	return out


class Report:
	"""Every source row's outcome, the counts, and the CSV written for the sign-off."""

	def __init__(self, kind: str, path: str, dry_run: int):
		self.kind, self.path, self.dry_run = kind, path, cint(dry_run)
		self.lines: list[dict] = []
		self.source_rows = 0

	def add(self, row, action: str, name: str | None = None, message: str = "") -> None:
		self.lines.append(
			{
				"row": row.get("_row") if isinstance(row, dict) else row,
				"sheet": row.get("_sheet", "") if isinstance(row, dict) else "",
				"key": row.get("_key", "") if isinstance(row, dict) else "",
				"action": action,
				"record": name or "",
				"message": cstr(message),
			}
		)

	def counts(self) -> dict:
		return {a: sum(1 for line in self.lines if line["action"] == a) for a in ACTIONS}

	def write(self, out: str | None = None) -> str:
		if not out:
			folder = frappe.get_site_path("private", REPORT_FOLDER)
			os.makedirs(folder, exist_ok=True)
			stamp = now_datetime().strftime("%Y%m%d-%H%M%S")
			mode = "dry-run" if self.dry_run else "run"
			out = os.path.join(folder, f"{self.kind}-{mode}-{stamp}.csv")
		buffer = io.StringIO()
		writer = csv.DictWriter(buffer, ["row", "sheet", "key", "action", "record", "message"])
		writer.writeheader()
		writer.writerows(self.lines)
		# the bench run's report, in the site's private folder or where the admin asked
		with open(out, "w", encoding="utf-8-sig", newline="") as f:  # nosemgrep
			f.write(buffer.getvalue())
		return out

	def result(self, out: str | None = None) -> dict:
		return {
			"kind": self.kind,
			"source": self.path,
			"dry_run": self.dry_run,
			"source_rows": self.source_rows,
			**self.counts(),
			"report": self.write(out),
		}


def run_rows(report: Report, items: list, save) -> None:
	"""save(item) for each item in its own savepoint: a failing row is rolled back and reported,
	and never stops the others. save returns (action, record name, message)."""
	for item in items:
		frappe.db.savepoint(ROW_SAVEPOINT)
		try:
			action, name, message = save(item)
		except Exception as e:
			frappe.db.rollback(save_point=ROW_SAVEPOINT)
			messages = [m.get("message") for m in frappe.local.message_log if isinstance(m, dict)]
			frappe.clear_messages()
			report.add(item, ERROR, None, cstr(e) or "; ".join(cstr(m) for m in messages if m))
			continue
		frappe.clear_messages()
		report.add(item, action, name, message)


def start(kind: str, path: str, dry_run) -> Report:
	check_admin()
	if not os.path.exists(path):
		frappe.throw(_("File {0} is not found.").format(path))
	frappe.db.savepoint(RUN_SAVEPOINT)
	return Report(kind, path, dry_run)


def finish(report: Report, out: str | None = None) -> dict:
	"""A dry run takes everything back; a real run is committed by bench when it returns."""
	if report.dry_run:
		frappe.db.rollback(save_point=RUN_SAVEPOINT)
	return report.result(out)


def fill(doc, values: dict) -> bool:
	"""Set the values the record does not have yet; True when something changed."""
	changed = False
	for field, value in values.items():
		if value in (None, "") or doc.get(field) not in (None, "", 0):
			continue
		doc.set(field, value)
		changed = True
	return changed


def list_value(list_name: str, value) -> str | None:
	"""An SP List Value of the list, by its name, code, Arabic or English value."""
	value = spaces(value)
	if not value:
		return None
	for field in ("name", "code", "value_ar", "value_en"):
		found = frappe.db.get_value("SP List Value", {"list_name": list_name, field: value})
		if found:
			return found
	return None
