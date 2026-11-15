"""SP-27: the five financial centers and the center map, each station's project tagged (back-link
and the Projects center), and the advance rows of the Account Map that SP-121 seeded moved to the
document's center (a station's advance posts to Projects)."""

import frappe

from smart_power.constants import SETTINGS_DOCTYPE
from smart_power.sp_core.services.company import COMPANY_SETTINGS

SEEDED_NOTE = "The official account comes from the advance."
ADVANCE_EVENTS = ("Customer Advance", "Advance Repayment", "Advance Fee")


def execute():
	from smart_power.sp_finance.centers import seed_centers, tag_project

	company = frappe.db.get_single_value(COMPANY_SETTINGS, "company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if not company:
		return
	seed_centers(company)
	for name in frappe.get_all("SP Station", {"project": ("is", "set")}, pluck="name"):
		tag_project(frappe.get_doc("SP Station", name))
	for row in frappe.get_all(
		"SP Account Map",
		{"parent": SETTINGS_DOCTYPE, "event": ("in", ADVANCE_EVENTS), "note": SEEDED_NOTE},
		pluck="name",
	):
		frappe.db.set_value(
			"SP Account Map",
			row,
			{"debit_center_rule": "From document", "credit_center_rule": "From document"},
		)
	frappe.clear_document_cache(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE)
