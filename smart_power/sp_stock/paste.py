"""Line-item grid (SP-44, component 7): rows pasted from Excel, items matched by code.

    match_items(codes)   {code as typed: item_code} for the codes found, and the ones not found

A code is matched as the item's code (any case, spacing ignored), then by the item's search key
(its code, names and model in one spelling, SP-41), so a model or an Arabic name also finds it
when it names exactly one item.
"""

import frappe

from smart_power.sp_core.search_key import normalize

MAX_ROWS = 500  # sp-allow-number: one paste, more than any quote or order holds


@frappe.whitelist()
def match_items(codes: list | str) -> dict:
	frappe.has_permission("Item", "read", throw=True)
	codes = frappe.parse_json(codes) if isinstance(codes, str) else codes
	codes = [str(c).strip() for c in (codes or [])[:MAX_ROWS] if str(c).strip()]
	found, missing = {}, []
	for code in dict.fromkeys(codes):  # each distinct code once, in order
		item = _match(code)
		if item:
			found[code] = item
		else:
			missing.append(code)
	return {"found": found, "missing": missing}


def _match(code: str) -> str | None:
	exact = frappe.db.get_value("Item", {"item_code": code, "disabled": 0}) or frappe.db.get_value(
		"Item", {"item_code": code.replace(" ", ""), "disabled": 0}
	)
	if exact:
		return exact
	key = normalize(code)
	rows = frappe.get_all(
		"Item",
		filters={"sp_search_key": ("like", f"%{key}%"), "disabled": 0},
		pluck="name",
		limit=2,  # sp-allow-number: is one item enough to know it is unique
	)
	return rows[0] if len(rows) == 1 else None  # only an unambiguous match
