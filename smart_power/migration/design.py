"""Design data for the design tools (T1, SP-159): DESIGN.xlsx into the items' specs.

    run(path, dry_run=1)

    PANEL   one column per panel model, brands across the top: the model, maximum power, Vmp,
            Imp, Voc and Isc become the item's watt and electrical specs
    DRIVE   one row per drive: the MPPT range (from, to) and the maximum DC input voltage

An item is found by its model (SP-165's sp_model, any spacing or case); a drive by the longest
model found in its name. A model with no item is reported: import it with its group first.
The sheet's own figures win, so a second run changes nothing.
"""

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.migration import common

KIND = "design"
PANEL, DRIVE = "PANEL", "DRIVE"
LABEL_COLUMN = 1  # sp-allow-number: the sheet's labels are in column B
PANEL_ROWS = {  # the label's start → the spec; Vmp comes before Imp in the sheet
	"brande": "brand",
	"module": "model",
	"maximumpo": "sp_watt",
	"opencircu": "sp_voc",
	"shortcirc": "sp_isc",
}
OPTIMUM = ("sp_vmp", "sp_imp")
PANEL_SPECS = ("sp_watt", "sp_vmp", "sp_imp", "sp_voc", "sp_isc")
DRIVE_SPECS = ("sp_mppt_min", "sp_mppt_max", "sp_max_dc_v")
MPPT_LABEL, MAX_DC_LABEL, ITEM_LABEL = "mpptrange", "vindc", "item"
FIRST_BELOW = 2  # sp-allow-number: the row under the header, numbered from 1


def _models() -> dict:
	index = {}
	for row in frappe.get_all("Item", {"sp_model": ("is", "set"), "disabled": 0}, ["name", "sp_model"]):
		index.setdefault(common.key(row.sp_model), row.name)
	return index


def panel_rows(cells: list[list]) -> list[dict]:
	where, optimum = {}, 0
	for number, values in enumerate(cells):
		label = common.key(values[LABEL_COLUMN] if len(values) > LABEL_COLUMN else "")
		for start, spec in PANEL_ROWS.items():
			if label.startswith(start) and spec not in where:
				where[spec] = number
		if label.startswith("optimumop") and optimum < len(OPTIMUM):
			where[OPTIMUM[optimum]] = number
			optimum += 1
	if "model" not in where:
		return []
	out, brand = [], ""
	width = max(len(r) for r in cells)
	for col in range(LABEL_COLUMN + 1, width):

		def cell(spec, c=col):
			return cells[where[spec]][c] if spec in where and c < len(cells[where[spec]]) else None

		brand = common.spaces(cell("brand")) or brand
		model = common.spaces(cell("model"))
		if model:
			out.append(
				{
					"_sheet": PANEL,
					"_row": where["model"] + 1,
					"_col": col + 1,
					"_key": model,
					"brand": brand,
					**{spec: flt(cell(spec)) or None for spec in PANEL_SPECS},
				}
			)
	return out


def drive_rows(cells: list[list]) -> list[dict]:
	header = next((n for n, r in enumerate(cells) if any(common.key(c) == ITEM_LABEL for c in r)), None)
	if header is None:
		return []
	labels = [common.key(c) for c in cells[header]]
	mppt = next((i for i, c in enumerate(labels) if c.startswith(MPPT_LABEL)), None)
	max_dc = next((i for i, c in enumerate(labels) if MAX_DC_LABEL in c), None)
	out = []
	for number, values in enumerate(cells[header + 1 :], start=header + FIRST_BELOW):
		name = common.spaces(values[LABEL_COLUMN] if len(values) > LABEL_COLUMN else "")
		if not name:
			continue
		get = lambda i, v=values: flt(v[i]) if i is not None and i < len(v) else 0.0  # noqa: E731
		out.append(
			{
				"_sheet": DRIVE,
				"_row": number,
				"_key": name,
				"sp_mppt_max": get(mppt) or None,
				"sp_mppt_min": get(mppt + 1 if mppt is not None else None) or None,
				"sp_max_dc_v": get(max_dc) or None,
			}
		)
	return out


def run(path: str, dry_run: int = 1, report: str | None = None) -> dict:
	result = common.start(KIND, path, dry_run)
	sheets = common._workbook_rows(path)
	panels, drives = panel_rows(sheets.get(PANEL, [])), drive_rows(sheets.get(DRIVE, []))
	result.source_rows = len(panels) + len(drives)
	models = _models()
	common.run_rows(result, panels, lambda row: _save(row, models.get(common.key(row["_key"])), PANEL_SPECS))
	common.run_rows(result, drives, lambda row: _save(row, _drive_item(row["_key"], models), DRIVE_SPECS))
	return common.finish(result, report)


def _drive_item(name: str, models: dict) -> str | None:
	text = common.key(name)
	found = [(len(model), item) for model, item in models.items() if model and model in text]
	return max(found)[1] if found else None


def _save(row: dict, item: str | None, specs: tuple) -> tuple:
	if not item:
		return (
			common.SKIPPED,
			None,
			_("No item has the model {0}: import it with its group first.").format(row["_key"]),
		)
	doc = frappe.get_doc("Item", item)
	changed = False
	for spec in specs:
		value = row.get(spec)
		if value is not None and flt(doc.get(spec)) != flt(value):
			doc.set(spec, value)
			changed = True
	if not changed:
		return common.UNCHANGED, item, ""
	doc.flags.ignore_permissions = True
	doc.save()
	return common.UPDATED, item, ""
