"""Vehicles (SP-159): the winch and the Jumbo car, with their odometer and oil interval.

    template(out)            the vehicles template
    run(path, dry_run=1)     the filled template

A vehicle is its licence plate. The odometer and the oil figures are the count on the day: a
second run updates them (the plate stays), so the last count wins.
"""

import frappe
from frappe import _
from frappe.utils import cint

from smart_power.migration import common
from smart_power.sp_winch.vehicles import JUMBO_TYPE, OTHER_TYPE, WINCH_TYPE

KIND = "vehicles"
COLUMNS = (
	("plate", "رقم اللوحة", "licence plate"),
	("kind", "النوع (ونش / جامبو / أخرى)", "type"),
	("odometer", "العداد (كم)", "odometer km"),
	("oil_interval", "تغيير الزيت كل (كم)", "oil interval km"),
	("last_oil", "آخر تغيير زيت عند (كم)", "last oil change km"),
	("driver", "السائق (مستخدم)", "driver user"),
	("notes", "ملاحظات", "notes"),
)
KINDS = {
	common.key(spelling): kind
	for kind, spellings in (
		(WINCH_TYPE, ("ونش", "winch")),
		(JUMBO_TYPE, ("جامبو", "jumbo")),
		(OTHER_TYPE, ("أخرى", "other")),
	)
	for spelling in spellings
}
COUNTS = ("sp_odometer_km", "sp_oil_interval_km", "sp_last_oil_km")


def template(out: str) -> str:
	return common.template(COLUMNS, out)


def run(path: str, dry_run: int = 1, company: str | None = None, report: str | None = None) -> dict:
	result = common.start(KIND, path, dry_run)
	company = company or frappe.db.get_single_value("Global Defaults", "default_company")
	rows = common.read(path, COLUMNS)
	result.source_rows = len(rows)
	items, seen = [], {}
	for row in rows:
		row["plate"] = common.spaces(row.get("plate"))
		row["_key"] = row["plate"]
		if not row["plate"]:
			result.add(row, common.ERROR, None, _("No licence plate."))
		elif row["plate"] in seen:
			result.add(row, common.SKIPPED, None, _("Repeats row {0}.").format(seen[row["plate"]]))
		else:
			seen[row["plate"]] = row["_row"]
			items.append(row)
	common.run_rows(result, items, lambda row: _save(row, company))
	return common.finish(result, report)


def _save(row: dict, company: str) -> tuple:
	kind = KINDS.get(common.key(row.get("kind"))) if row.get("kind") else None
	if row.get("kind") and not kind:
		frappe.throw(_("Type {0} is not ونش, جامبو or أخرى.").format(row.get("kind")))
	driver = row.get("driver")
	if driver and not frappe.db.exists("User", driver):
		frappe.throw(_("{0} is not a user.").format(driver))
	counts = {
		"sp_odometer_km": cint(row.get("odometer")) or None,
		"sp_oil_interval_km": cint(row.get("oil_interval")) or None,
		"sp_last_oil_km": cint(row.get("last_oil")) or None,
	}
	others = {"sp_vehicle_type": kind, "sp_driver_user": driver, "sp_notes": row.get("notes")}
	if frappe.db.exists("Vehicle", row["plate"]):
		doc = frappe.get_doc("Vehicle", row["plate"])
		changed = common.fill(doc, others)
		for field, value in counts.items():
			if value is not None and cint(doc.get(field)) != value:
				doc.set(field, value)
				changed = True
		if not changed:
			return common.UNCHANGED, doc.name, ""
		doc.flags.ignore_permissions = True
		doc.save()
		return common.UPDATED, doc.name, ""
	doc = frappe.get_doc(
		{
			"doctype": "Vehicle",
			"license_plate": row["plate"],
			"company": company,
			"sp_vehicle_type": kind or OTHER_TYPE,
			**{k: v for k, v in {**counts, **others}.items() if v not in (None, "")},
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return common.CREATED, doc.name, ""
