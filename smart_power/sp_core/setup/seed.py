"""Seed values from defaults.json. Loaded once on install; a later deploy never overwrites them."""

import json
import os
from functools import cache

import frappe

from smart_power.constants import SETTINGS_DOCTYPE


@cache
def defaults() -> dict:
	path = os.path.join(os.path.dirname(__file__), "defaults.json")
	# A fixed file inside the app.
	with open(path, encoding="utf-8") as f:  # nosemgrep
		return json.load(f)


def _clean(row: dict) -> dict:
	return {k: v for k, v in row.items() if not k.startswith("_")}


def seed_rule_values() -> dict:
	return {k: _clean(v) for k, v in defaults().get("rule_settings", {}).items()}


def seed_settings(force: bool = False) -> None:
	"""Fill Smart Power Settings from the seed, only where the admin has not set a value."""
	doc = frappe.get_single(SETTINGS_DOCTYPE)
	data = defaults()
	for fieldname, spec in data.get("settings", {}).items():
		if force or doc.get(fieldname) in (None, "", 0):
			doc.set(fieldname, spec["value"])
	if force or not doc.margin_ranges:
		doc.set("margin_ranges", [])
		for row in data.get("margin_ranges", []):
			doc.append("margin_ranges", _clean(row))
	doc.flags.ignore_permissions = True
	doc.flags.sp_seed = True
	doc.save()


def seed_list_values() -> None:
	"""Create the seed list values that are missing (matched by list and code)."""
	for row in defaults().get("list_values", []):
		row = _clean(row)
		if frappe.db.exists("SP List Value", {"list_name": row["list_name"], "code": row["code"]}):
			continue
		frappe.get_doc({"doctype": "SP List Value", "is_active": 1, **row}).insert(ignore_permissions=True)
