"""Fixture ownership checks and the admin backup (SP-164).

- `preflight()` runs before every migrate. It refuses the deploy when a developer fixture
  would overwrite a record the admin owns, and reports developer records the admin edited
  in place (those revert to the shipped version; the runbook says how to keep the change).
- `backup_admin_customizations()` runs nightly and saves the admin's customizations as a
  private JSON file, for audit and restore.
"""

import glob
import json
import os

import frappe
from frappe.utils import get_datetime, now_datetime

from smart_power.constants import (
	DEV_NAME_PREFIX,
	MODULE_OWNED_DOCTYPES,
	PREFIX_OWNED_DOCTYPES,
	SP_MODULES,
)


class FixtureConflict(frappe.ValidationError):
	pass


def fixture_records(app: str = "smart_power") -> list[dict]:
	records = []
	for path in sorted(glob.glob(os.path.join(frappe.get_app_path(app, "fixtures"), "*.json"))):
		# Paths come from the app's own fixtures folder.
		with open(path, encoding="utf-8") as f:  # nosemgrep
			data = json.load(f)
		for rec in data if isinstance(data, list) else [data]:
			rec["_file"] = os.path.basename(path)
			records.append(rec)
	return records


def check(records: list[dict] | None = None) -> dict:
	"""Compare the app fixtures with the site. Returns {"conflicts": [...], "drift": [...]}."""
	records = fixture_records() if records is None else records
	conflicts, drift = [], []
	for rec in records:
		dt, name = rec.get("doctype"), rec.get("name")
		if not dt or not name or not frappe.db.table_exists(dt):
			continue
		if dt in PREFIX_OWNED_DOCTYPES and not name.startswith(DEV_NAME_PREFIX):
			conflicts.append(f"{dt} {name!r}: developer fixtures may only hold names starting with 'SP '")
			continue
		if not frappe.db.exists(dt, name):
			continue
		if dt in MODULE_OWNED_DOCTYPES:
			module = frappe.db.get_value(dt, name, "module")
			if module not in SP_MODULES:
				conflicts.append(f"{dt} {name!r} is owned by {module or 'the admin (no module)'}")
				continue
		db_modified = frappe.db.get_value(dt, name, "modified")
		if rec.get("modified") and db_modified and get_datetime(db_modified) > get_datetime(rec["modified"]):
			drift.append(f"{dt} {name!r} was changed on the site after the shipped version")
	return {"conflicts": conflicts, "drift": drift}


def preflight(raise_on_conflict: bool = True) -> dict:
	result = check()
	for line in result["drift"]:
		print(f"[smart_power] drift: {line} - this deploy restores the shipped version")
	if result["conflicts"]:
		message = "Deploy stopped: a developer fixture would overwrite the admin's change.\n" + "\n".join(
			result["conflicts"]
		)
		print(f"[smart_power] {message}")
		if raise_on_conflict:
			raise FixtureConflict(message)
	return result


STANDARD_FLAG = {
	"Report": ("is_standard", "Yes"),
	"Print Format": ("standard", "Yes"),
	"Notification": ("is_standard", 1),
}


def admin_customizations() -> dict:
	"""Every customization not owned by the developer, grouped by DocType."""
	out: dict[str, list] = {}
	for dt in MODULE_OWNED_DOCTYPES:
		if not frappe.db.table_exists(dt):
			continue
		rows = frappe.get_all(dt, fields=["name", "module"])
		names = [r.name for r in rows if r.module not in SP_MODULES]
		if dt in STANDARD_FLAG:
			field, value = STANDARD_FLAG[dt]
			names = [n for n in names if frappe.db.get_value(dt, n, field) != value]
		out[dt] = [frappe.get_doc(dt, n).as_dict() for n in sorted(names)]
	names = frappe.get_all(
		"Role Profile", filters={"name": ("not like", DEV_NAME_PREFIX + "%")}, pluck="name"
	)
	out["Role Profile"] = [frappe.get_doc("Role Profile", n).as_dict() for n in sorted(names)]
	# every workflow: the SP ones are the admin's to change too, since SP-133 seeds them only once
	out["Workflow"] = [
		frappe.get_doc("Workflow", n).as_dict() for n in sorted(frappe.get_all("Workflow", pluck="name"))
	]
	out["Custom DocPerm"] = frappe.get_all("Custom DocPerm", fields=["*"], order_by="parent, role")
	return out


def backup_admin_customizations() -> str:
	"""Nightly job: save the admin's customizations as a private file. Returns the file URL."""
	content = json.dumps(admin_customizations(), default=str, ensure_ascii=False, indent=1)
	stamp = now_datetime().strftime("%Y-%m-%d")
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"sp-admin-customizations-{stamp}.json",
			"is_private": 1,
			"content": content,
			"folder": "Home",
		}
	).insert(ignore_permissions=True)
	return file.file_url
