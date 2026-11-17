"""Q1 quotes list (SP-64): what the list shows of each quote, kept in step with its case.

- sp_follow_up_owner, sp_system_type and sp_size (kW or HP) come from the case, so the list can
  show and filter them; a change on the case reaches its quotes.
- sp_is_latest marks the newest live version of each quote (its chain of versions, sp_root): the
  list shows only those by default, and a toggle shows every version.
- The margin column is the cost permlevel's: the list and its export leave it out for whoever
  may not read it (the follow-up roles).
"""

import json

import frappe
from frappe.model.docstatus import DocStatus
from frappe.utils import flt

QUOTATION, CASE = "Quotation", "SP Case"
CANCELLED = DocStatus.cancelled()
SIZE_KEYS = (("kw", "kW"), ("hp", "HP"))
CASE_FIELDS = ("follow_up_owner", "system_types", "request_details")


def _case_values(case: str | None) -> dict:
	"""{sp_follow_up_owner, sp_system_type, sp_size} for a case."""
	if not case or not frappe.db.exists(CASE, case):
		return {"sp_follow_up_owner": None, "sp_system_type": None, "sp_size": None}
	row = frappe.db.get_value(CASE, case, ["follow_up_owner", "request_details"], as_dict=True)
	system_type = frappe.db.get_value(
		"SP Case System Type", {"parent": case, "parenttype": CASE}, "system_type", order_by="idx asc"
	)
	return {
		"sp_follow_up_owner": row.follow_up_owner,
		"sp_system_type": system_type,
		"sp_size": size_of(row.request_details),
	}


def size_of(details, design_inputs=None) -> str | None:
	""" "15 kW" or "20 HP" from the request (or the quote's design inputs)."""
	for source in (details, design_inputs):
		if isinstance(source, str):
			try:
				source = json.loads(source or "{}")
			except ValueError:
				source = {}
		for key, unit in SIZE_KEYS:
			value = flt((source or {}).get(key))
			if value:
				return f"{value:g} {unit}"
	return None


def set_list_fields(doc, method=None) -> None:
	"""Quotation validate: the case's follow-up owner, system and size, and whether this is the
	newest version of its chain (set here too, so a later save never writes a stale flag)."""
	values = _case_values(doc.get("sp_case"))
	if not values["sp_size"]:
		values["sp_size"] = size_of(None, doc.get("sp_design_inputs"))
	doc.update(values)
	doc.sp_is_latest = 0 if _newer_version(doc) else 1


def _newer_version(doc) -> bool:
	if not doc.get("sp_root"):
		return False  # the first version of a new chain
	return bool(
		frappe.db.exists(
			QUOTATION,
			{
				"sp_root": doc.sp_root,
				"docstatus": ("<", CANCELLED),
				"sp_version": (">", doc.get("sp_version") or 0),
				"name": ("!=", doc.name or ""),
			},
		)
	)


def refresh_latest(root: str | None, leaving: str | None = None) -> None:
	"""Mark the newest live version of a chain as the latest, the others not (`leaving`: a
	version being deleted)."""
	if not root:
		return
	versions = frappe.get_all(
		QUOTATION,
		{"sp_root": root, "docstatus": ("<", CANCELLED), "name": ("!=", leaving or "")},
		["name", "sp_is_latest"],
		order_by="sp_version desc, creation desc",
	)
	for i, v in enumerate(versions):
		latest = 1 if i == 0 else 0
		if v.sp_is_latest != latest:
			frappe.db.set_value(QUOTATION, v.name, "sp_is_latest", latest, update_modified=False)
	# a cancelled version is never the latest
	for name in frappe.get_all(
		QUOTATION, {"sp_root": root, "docstatus": CANCELLED, "sp_is_latest": 1}, pluck="name"
	):
		frappe.db.set_value(QUOTATION, name, "sp_is_latest", 0, update_modified=False)


def on_quote_change(doc, method=None) -> None:
	"""Quotation after_insert / on_cancel / on_trash: the chain's latest moves."""
	root = doc.get("sp_root") or (doc.name if method == "after_insert" else None)
	leaving = doc.name if method == "on_trash" else None
	refresh_latest(root, leaving)


def on_case_change(doc, method=None) -> None:
	"""SP Case on_update: its quotes follow the follow-up owner, system and size."""
	before = doc.get_doc_before_save()
	if before and all(_same(before.get(f), doc.get(f)) for f in CASE_FIELDS):
		return
	values = _case_values(doc.name)
	for q in frappe.get_all(QUOTATION, {"sp_case": doc.name}, ["name", "sp_design_inputs"]):
		row = dict(values)
		if not row["sp_size"]:
			row["sp_size"] = size_of(None, q.sp_design_inputs)
		frappe.db.set_value(QUOTATION, q.name, row, update_modified=False)


def _same(a, b) -> bool:
	if isinstance(a, list) or isinstance(b, list):
		return [r.get("system_type") for r in a or []] == [r.get("system_type") for r in b or []]
	return (a or None) == (b or None)


def backfill() -> None:
	"""Fill the list fields and the latest flags on the quotes that exist (patch)."""
	for q in frappe.get_all(QUOTATION, {"sp_case": ("is", "set")}, ["name", "sp_case", "sp_design_inputs"]):
		row = _case_values(q.sp_case)
		if not row["sp_size"]:
			row["sp_size"] = size_of(None, q.sp_design_inputs)
		frappe.db.set_value(QUOTATION, q.name, row, update_modified=False)
	for root in frappe.get_all(QUOTATION, {"sp_root": ("is", "set")}, pluck="sp_root", distinct=True):
		refresh_latest(root)
