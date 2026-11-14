"""SP-134: tasks, review items and rule overrides get their own yearly counter, starting after
the highest number each already used."""

import frappe

from smart_power.sp_core.numbering import start_counters_after_used


def execute():
	for doctype in ("SP Task", "SP Review Item", "SP Rule Override Log"):
		frappe.reload_doc("sp_core", "doctype", frappe.scrub(doctype))
	start_counters_after_used()
