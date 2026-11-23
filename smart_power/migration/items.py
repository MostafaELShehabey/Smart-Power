"""Items and their dated prices (SP-159), through SP-165's per-group templates.

    run(path, dry_run=1, item_group=None)

One sheet per item group, named by the group or its code prefix (PNL, INV …); with item_group,
the file's one sheet is that group. SP-165 cleans each row (spellings, codes, required specs) and
reports duplicate codes and prices without a date or a supplier; the clean rows go through the
item import (SP-29) and the price import (SP-30), so P1, BTB and BTC each keep their date.
"""

import os

import frappe
from frappe import _

from smart_power.migration import common
from smart_power.sp_stock import item_codes

KIND = "items"


def _group(title: str, given: str | None) -> str | None:
	if given:
		return given if frappe.db.exists("Item Group", given) else None
	title = common.spaces(title)
	if frappe.db.exists("Item Group", title):
		return title
	return frappe.db.get_value("Item Group", {"sp_code_prefix": title.upper()})


def run(path: str, dry_run: int = 1, item_group: str | None = None, report: str | None = None) -> dict:
	result = common.start(KIND, path, dry_run)
	source = os.path.basename(path)
	for title, rows in common._workbook_rows(path).items():
		group = _group(title, item_group)
		data = [r for r in rows[1:] if any(common.cstr(c).strip() for c in r)]
		result.source_rows += len(data)
		if not group:
			result.add(
				{"_sheet": title}, common.ERROR, None, _("Sheet {0} is not an item group.").format(title)
			)
			continue
		checked = item_codes.check_rows(rows, group)
		existed = {
			r["item_code"] for r in checked if r.get("item_code") and frappe.db.exists("Item", r["item_code"])
		}
		done = item_codes.import_checked(rows, group, int(result.dry_run), source=source)
		for r in done["rows"]:
			line = {"_row": r["row"], "_sheet": title, "_key": r.get("item_code") or ""}
			message = "; ".join(common.cstr(m) for m in r.get("messages") or [])
			if r["status"] == item_codes.OK:
				action = common.UPDATED if r.get("item_code") in existed else common.CREATED
			elif r["status"] == item_codes.DUPLICATE:
				action = common.SKIPPED
			else:
				action = common.ERROR
			result.add(line, action, r.get("item_code"), message)
	return common.finish(result, report)
