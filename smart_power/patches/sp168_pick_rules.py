"""SP-168: panels from stock first and the pump by its curve; open drafts keep today's brand order."""

import json

import frappe

from smart_power.sp_core.services.settings import brand_order
from smart_power.sp_quotes.calc_templates import add_pick_rules


def execute():
	from frappe.utils.fixtures import sync_fixtures

	sync_fixtures("smart_power")  # the quote's new field comes with the fixtures, synced after patches
	add_pick_rules()
	order = json.dumps(brand_order(), ensure_ascii=False)
	for name in frappe.get_all("Quotation", {"docstatus": 0, "sp_case": ("is", "set")}, pluck="name"):
		if not frappe.db.get_value("Quotation", name, "sp_brand_order"):
			frappe.db.set_value("Quotation", name, "sp_brand_order", order, update_modified=False)
