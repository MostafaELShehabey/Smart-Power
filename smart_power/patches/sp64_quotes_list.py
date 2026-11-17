"""SP-64: the Q1 list fields on the quotes that exist, and the quotes' saved views.

The new custom fields come with the fixtures, which migrate syncs after the patches: sync them
first. The Quotation saved views are seed rows: their filters move to the latest versions, and
"Expiring in 48 h" and "Accepted" are added."""

import json

import frappe


def execute():
	from frappe.utils.fixtures import sync_fixtures

	from smart_power.lists import VIEW, seed_list_views
	from smart_power.sp_core.setup.seed import defaults
	from smart_power.sp_sales.quote_list import backfill

	sync_fixtures("smart_power")
	for row in defaults()["list_views"]["views"]:
		if row["list_doctype"] != "Quotation":
			continue
		name = frappe.db.get_value(VIEW, {"list_doctype": "Quotation", "label": row["label"]})
		if name:
			frappe.db.set_value(
				VIEW,
				name,
				{"filters": json.dumps(row["filters"], ensure_ascii=False), "sort_order": row["sort_order"]},
			)
	seed_list_views()
	backfill()
