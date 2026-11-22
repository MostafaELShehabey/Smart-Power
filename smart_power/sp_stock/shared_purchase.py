"""Shared purchases (SP-83): one order split between stations by amount (a cable drum, say).

The purchase officer enters each station's amount on the order (SP PO Station Split). The
amounts must add up to the order's total (to the pound), and the goods go to a store, not to one
station's site. Each station needs its project.

When the technical office confirms a receipt of the order (SP-85, P4), its value is shared between
the stations in the same proportions. The allocation is record-only (owner, 2026-11-22): nobody
transfers or logs the goods to the sites. The system posts it:

    Stock Entry     Material Issue of the received stock lines, out of the store, to the
                    Shared Purchases account (no project)
    Journal Entry   event "Shared Purchase Split" from the Account Map:
                      Dr Project Materials   each station's share, on its project (Projects center)
                      Cr Shared Purchases    the issued value, so the account nets 0
                      Cr a non-stock line's own expense account, for its billed value

so each station's actual cost rises by its share, under "purchases" (SP-76). A receipt of only
part of the order shares only what arrived. Cancelling the receipt cancels both.
"""

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.sp_finance.centers import PROJECTS, center

ORDER, RECEIPT, STATION = "Purchase Order", "Purchase Receipt", "SP Station"
SPLITS = "sp_station_splits"
ISSUE_FIELD = "sp_shared_issue"
EVENT = "Shared Purchase Split"
SHARED_ACCOUNT, STATION_ACCOUNT = "Shared Purchases", "Project Materials"
TOLERANCE = 1  # sp-allow-number: the story's ±1 EGP when the splits are checked against the total
MONEY_DIGITS = 2  # sp-allow-number: currency precision


# --- the order ------------------------------------------------------------------------------------


def validate_order(doc, method=None) -> None:
	"""Purchase Order validate: the stations' amounts add up to the order's total."""
	splits = doc.get(SPLITS) or []
	if not splits:
		return
	if doc.get("sp_station") or any(row.get("sp_station") for row in doc.items):
		frappe.throw(
			_("A shared order goes to a store. Put its stations in the split, not on the order or its rows."),
			title=_("Shared between stations"),
		)
	seen = set()
	for row in splits:
		if row.station in seen:
			frappe.throw(_("Station {0} is in the split twice.").format(frappe.bold(row.station)))
		seen.add(row.station)
		company, project = frappe.db.get_value(STATION, row.station, ["company", "project"]) or (None, None)
		if company and company != doc.company:
			frappe.throw(_("Station {0} belongs to another company.").format(frappe.bold(row.station)))
		if not project:
			frappe.throw(_("Station {0} has no project yet.").format(frappe.bold(row.station)))
		row.project = project
		if flt(row.amount) <= 0:
			frappe.throw(_("Give station {0} its amount.").format(frappe.bold(row.station)))
	total, split = flt(doc.base_net_total), sum(flt(r.amount) for r in splits)
	if abs(total - split) > TOLERANCE:
		frappe.throw(
			_("The stations' amounts add up to {0}, not the order's total of {1}.").format(
				frappe.format(split, "Currency"), frappe.format(total, "Currency")
			),
			title=_("Shared between stations"),
		)


def _splits(order: str) -> list:
	return frappe.get_all(
		"SP PO Station Split",
		{"parent": order, "parenttype": ORDER, "parentfield": SPLITS},
		["station", "project", "amount"],
		order_by="idx asc",
	)


# --- the receipt ----------------------------------------------------------------------------------


def _account(company: str, name: str) -> str | None:
	return frappe.db.get_value("Account", {"company": company, "account_name": name, "is_group": 0})


def _accounts(company: str) -> tuple[str, str]:
	from smart_power.sp_core.services.settings import account_map

	row = account_map(EVENT)

	def of(name, mapped):
		if mapped and frappe.db.get_value("Account", mapped, "company") == company:
			return mapped
		return _account(company, name)

	debit = of(STATION_ACCOUNT, row.debit_account if row else None)
	credit = of(SHARED_ACCOUNT, row.credit_account if row else None)
	if not (debit and credit):
		frappe.throw(
			_("Map the Shared Purchase Split event in Smart Power Settings > Account Map."),
			title=_("Account Map"),
		)
	return debit, credit


def _issue(doc, shared: str) -> tuple[str | None, float]:
	"""The received stock lines leave the store; their value lands on the Shared Purchases account."""
	stock = [r for r in doc.items if frappe.get_cached_value("Item", r.item_code, "is_stock_item")]
	if not stock:
		return None, 0.0
	cost_center = frappe.get_cached_value("Company", doc.company, "cost_center")
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Issue",
			"purpose": "Material Issue",
			"company": doc.company,
			"posting_date": doc.posting_date,
			"posting_time": doc.posting_time,
			"set_posting_time": 1,
			"remarks": _("Shared between stations: {0}").format(doc.name),
			"items": [
				{
					"item_code": r.item_code,
					"qty": flt(r.stock_qty),
					"uom": r.stock_uom,
					"stock_uom": r.stock_uom,
					"conversion_factor": 1,
					"s_warehouse": r.warehouse,
					"expense_account": shared,
					"cost_center": cost_center,
					"use_serial_batch_fields": 1 if r.serial_no else 0,
					"serial_no": r.serial_no,
				}
				for r in stock
			],
		}
	)
	se.flags.ignore_permissions = True  # the confirmer's right is checked by the caller
	se.insert()
	se.submit()
	return se.name, flt(se.total_outgoing_value)


def _billed_services(invoice: str) -> list[dict]:
	"""The invoice's non-stock lines: they posted to their own expense account."""
	rows = frappe.get_all(
		"Purchase Invoice Item",
		{"parent": invoice},
		["item_code", "expense_account", "cost_center", "base_net_amount"],
	)
	return [r for r in rows if not frappe.get_cached_value("Item", r.item_code, "is_stock_item")]


def shares(total: float, splits: list) -> list[float]:
	"""The total in the splits' proportions; the last station takes the rounding."""
	whole = sum(flt(s.amount) for s in splits)
	out = [flt(total * flt(s.amount) / whole, MONEY_DIGITS) for s in splits[:-1]]
	return [*out, flt(total - sum(out), MONEY_DIGITS)]


def allocate(doc, invoice: str) -> str | None:
	"""At confirmation: the receipt's value goes to the stations of its order's split."""
	from smart_power.sp_finance.custody import _journal

	splits = _splits(doc.sp_purchase_order) if doc.get("sp_purchase_order") else []
	if not splits:
		return None
	debit, shared = _accounts(doc.company)
	issue, issued = _issue(doc, shared)
	credits = [{"account": shared, "credit_in_account_currency": issued}] if issued else []
	for line in _billed_services(invoice):
		credits.append(
			{
				"account": line.expense_account,
				"credit_in_account_currency": flt(line.base_net_amount),
				"cost_center": line.cost_center,
			}
		)
	total = sum(flt(c["credit_in_account_currency"]) for c in credits)
	if issue:
		doc.db_set(ISSUE_FIELD, issue, update_modified=False)
	if total <= 0:
		return None
	projects = center(PROJECTS, doc.company)
	debits = [
		{
			"account": debit,
			"debit_in_account_currency": amount,
			"cost_center": projects,
			"project": split.project,
			"user_remark": split.station,
		}
		for split, amount in zip(splits, shares(total, splits), strict=True)
		if amount
	]
	frappe.flags.sp_system_posting = True  # the posting is the system's (SP-26)
	try:
		return _journal(
			doc,
			doc.posting_date,
			debits + credits,
			EVENT,
			_("Purchase {0} shared between stations ({1})").format(doc.sp_purchase_order, doc.name),
		)
	finally:
		frappe.flags.sp_system_posting = False


def before_cancel_receipt(doc, method=None) -> None:
	"""Purchase Receipt before_cancel: the shared goods come back to the store first."""
	issue = doc.get(ISSUE_FIELD)
	if issue and frappe.db.get_value("Stock Entry", issue, "docstatus") == 1:
		se = frappe.get_doc("Stock Entry", issue)
		se.flags.ignore_permissions = True
		se.flags.ignore_links = True  # the receipt being cancelled is what links to it
		se.cancel()


# --- setup ----------------------------------------------------------------------------------------


def seed_account_map(company: str) -> None:
	"""The Shared Purchase Split row of the Account Map, once. The admin can change it."""
	from smart_power.constants import SETTINGS_DOCTYPE

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if any(r.event == EVENT for r in settings.account_map):
		return
	debit, credit = _account(company, STATION_ACCOUNT), _account(company, SHARED_ACCOUNT)
	cc = frappe.get_cached_value("Company", company, "cost_center")
	if not (debit and credit and cc):
		return
	settings.append(
		"account_map",
		{
			"event": EVENT,
			"debit_account": debit,
			"debit_center_rule": "From document",
			"debit_cost_center": cc,
			"credit_account": credit,
			"credit_center_rule": "From document",
			"credit_cost_center": cc,
			"project_rule": "Debit side",
			"note": "A purchase shared between stations: each station's share of what was received.",
		},
	)
	settings.flags.ignore_permissions = True
	settings.save()
