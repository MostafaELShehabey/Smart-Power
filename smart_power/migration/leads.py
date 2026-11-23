"""Leads (SP-159): the marketing agent's leads, with their owner and campaign (SP-51's rules).

    run(path, owner, campaign=None, dry_run=1)

The columns are found by their names, as the lead import does (name, mobile, source …). A mobile
that is already a customer or a lead, or repeats in the file, is skipped and reported: a lead is
never merged. The leads are created as their owner (مها), so they are hers.
"""

import frappe
from frappe import _
from frappe.utils import cstr

from smart_power.migration import common
from smart_power.sp_sales import lead_import

KIND = "leads"


def run(
	path: str, owner: str, campaign: str | None = None, dry_run: int = 1, report: str | None = None
) -> dict:
	result = common.start(KIND, path, dry_run)
	if not frappe.db.exists("User", owner):
		frappe.throw(_("{0} is not a user.").format(owner))
	if campaign and not frappe.db.exists("SP Campaign", campaign):
		frappe.throw(_("Campaign {0} is not found.").format(campaign))
	rows = [
		[cstr(c) if c is not None else "" for c in r]
		for r in next(iter(common._workbook_rows(path).values()), [])
	]
	mapping = lead_import.guess_mapping(rows[0] if rows else [])
	missing = [f for f in lead_import.REQUIRED if f not in mapping]
	if missing:
		frappe.throw(_("The file has no column for: {0}.").format(", ".join(missing)))
	results = lead_import.classify(rows, mapping)
	result.source_rows = len(results)
	new = []
	for r in results:
		line = {"_row": r["row"], "_key": r["mobile"], **r}
		if r["status"] == lead_import.NEW:
			new.append(line)
		else:
			action = common.SKIPPED if r["status"] == lead_import.DUPLICATE else common.ERROR
			result.add(line, action, None, r.get("message"))
	current = frappe.session.user
	# her leads are made as her, as the lead import's job does
	frappe.set_user(owner)  # nosemgrep
	try:
		common.run_rows(result, new, lambda line: _save(line, campaign))
	finally:
		frappe.set_user(current)  # nosemgrep
	return common.finish(result, report)


def _save(line: dict, campaign: str | None) -> tuple:
	lead = frappe.get_doc({"doctype": "Lead", **line["values"], "sp_campaign": campaign or None})
	lead.insert()
	return common.CREATED, lead.name, ""
