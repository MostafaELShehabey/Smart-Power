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
FILES = ("pump.json",)


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
