"""Calculation templates shipped with the app (SP-56), one JSON file per offer type.

    seed_calc_templates()   creates each template that has no version yet, and publishes it
                            when its offer type has no published version

A template the admin already has (any version of its key) is never touched: from then on it is
their data, changed by making a new version.
"""

import json
import os

import frappe

from smart_power.sp_core.services.lists import by_code

TEMPLATE = "SP Calc Template"
FILES = ("pump.json", "offgrid.json", "ongrid.json")
PUMP_KEY, PUMP_FILE, DEPTH_INPUT = "PUMP", "pump.json", "pump_depth"
CURVE_INPUTS = ("required_head_m", "required_flow_m3h")  # SP-184
BRAND_PRIORITY = "Brand priority"
PICK_RULES = {"panels": "Stock first", "pump": "Pump curve"}  # SP-168


def template_data(file_name: str) -> dict:
	if file_name not in FILES:
		raise ValueError(file_name)
	# one of the fixed files shipped inside the app, never a name from a request
	with open(os.path.join(os.path.dirname(__file__), file_name), encoding="utf-8") as f:  # nosemgrep
		return json.load(f)


def seed_calc_templates() -> list[str]:
	"""Returns the names of the templates created."""
	created = []
	for file_name in FILES:
		data = template_data(file_name)
		if frappe.db.exists(TEMPLATE, {"template_key": data["template_key"]}):
			continue
		offer_type = by_code(*data["offer_type"])
		groups = {row["item_group"] for row in data["lines"] if row.get("item_group")}
		if not offer_type or not all(frappe.db.exists("Item Group", g) for g in groups):
			continue  # before the lists or the catalogue groups are seeded: a later run makes it
		doc = frappe.get_doc(
			{
				"doctype": TEMPLATE,
				"template_key": data["template_key"],
				"template_name": data["template_name"],
				"offer_type": offer_type,
				"description": data.get("description"),
				"inputs": data["inputs"],
				"lines": data["lines"],
			}
		).insert(ignore_permissions=True)
		if not frappe.db.exists(TEMPLATE, {"offer_type": offer_type, "is_published": 1}):
			doc.publish()
		created.append(doc.name)
	return created


def add_curve_inputs(template_key: str = PUMP_KEY) -> str | None:
	"""SP-184: the required head and flow, as a new published version of the pump template. The
	admin's published version is the base, so their changes stay; quotes keep the version they
	used. Returns the new version, or None when there is nothing to do."""
	published = frappe.db.get_value(TEMPLATE, {"template_key": template_key, "is_published": 1}, "name")
	if not published:
		return None
	source = frappe.get_doc(TEMPLATE, published)
	if set(CURVE_INPUTS) <= {row.input_key for row in source.inputs}:
		return None
	doc = frappe.get_doc(TEMPLATE, source.new_version())
	shipped = {row["input_key"]: row for row in template_data(PUMP_FILE)["inputs"]}
	have = {row.input_key for row in doc.inputs}
	for key in CURVE_INPUTS:
		if key not in have:
			doc.append("inputs", shipped[key])
	first = [row for row in doc.inputs if row.input_key not in CURVE_INPUTS]
	added = [row for row in doc.inputs if row.input_key in CURVE_INPUTS]
	at = next((i + 1 for i, row in enumerate(first) if row.input_key == DEPTH_INPUT), len(first))
	doc.inputs = [*first[:at], *added, *first[at:]]
	for idx, row in enumerate(doc.inputs, start=1):
		row.idx = idx
	doc.save(ignore_permissions=True)
	doc.publish()
	return doc.name


def add_pick_rules(template_key: str = PUMP_KEY) -> str | None:
	"""SP-168: panels from stock first and the pump by its curve, as a new published version. A
	line the admin moved to another rule keeps it. Returns the new version, or None."""
	published = frappe.db.get_value(TEMPLATE, {"template_key": template_key, "is_published": 1}, "name")
	if not published:
		return None
	source = frappe.get_doc(TEMPLATE, published)
	if not any(r.line_key in PICK_RULES and r.selection_rule == BRAND_PRIORITY for r in source.lines):
		return None
	doc = frappe.get_doc(TEMPLATE, source.new_version())
	for row in doc.lines:
		if row.line_key in PICK_RULES and row.selection_rule == BRAND_PRIORITY:
			row.selection_rule = PICK_RULES[row.line_key]
	doc.save(ignore_permissions=True)
	doc.publish()
	return doc.name
