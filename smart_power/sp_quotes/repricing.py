"""Repricing (SP-170, decision 55): a quote uses the prices of its day, and the deposit fixes them.

Every day, a sent quote with no confirmed deposit is flagged Needs repricing when it is past its
Valid Till or when pricing the same items today gives another rate than the one on the quote. The
price list keeps one current price per item, so the quote's own lines are the record of the prices
of its day. The same inputs, overrides and picked items are priced, so a typed price or a stock
change never looks like a price change, and the discount sits on the total, outside the lines.
The quote creator and the follow-up owner are told once.

Approving a flagged version follows the rule quote_old_price_approval: Block forces a new version;
Warn lets the admin honor the old price with a reason; Off allows it.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate, today

from smart_power.notify import send
from smart_power.permissions import sees_quote_internals
from smart_power.rules import (
	BLOCK,
	WARN,
	can_override,
	effective_level,
	evaluate,
	get_rule_setting,
	record_warning,
	registry,
)
from smart_power.rules.sales import OLD_PRICE_RULE, QUOTE_APPROVE_EVENT
from smart_power.sp_quotes.engine import calculate
from smart_power.sp_quotes.quote_calc import write_lines
from smart_power.sp_stock.prices import BTC, latest_price

QUOTATION, CASE, TEMPLATE = "Quotation", "SP Case", "SP Calc Template"
CHECKED_STATUSES = ("Sent", "Expired", "Approved")
CLOSED_CASES = ("Won", "Lost")  # a case is Won only by its confirmed deposit
EVENT = "quote_needs_repricing"
MONEY = 2  # sp-allow-number: amounts to the piastre
NOTE_ITEMS = 3  # sp-allow-number: the items a repricing note names


def _json(value) -> dict:
	return json.loads(value) if value else {}


def _picks(doc) -> dict:
	"""The items the quote's template lines chose, so a reprice compares the same items."""
	groups = {
		r.line_key
		for r in frappe.get_all(
			"SP Calc Template Line",
			{"parent": doc.sp_calc_template, "parenttype": TEMPLATE, "item_group": ("is", "set")},
			["line_key"],
		)
	}
	return {r.sp_line_key: r.item_code for r in doc.items if r.get("sp_line_key") in groups}


def _priced_today(doc) -> dict:
	result = calculate(
		doc.sp_calc_template,
		_json(doc.get("sp_design_inputs")),
		_json(doc.get("sp_calc_overrides")),
		on_date=today(),
		brands=_json(doc.get("sp_brand_order")) if doc.get("sp_brand_order") else None,
		picks=_picks(doc),
	)
	return {line.line_key: line for line in result.lines if not line.is_optional and not line.is_hidden}


def _change(row, key, qty, new_rate) -> dict:
	old, new = flt(row.qty) * flt(row.rate), flt(qty) * flt(new_rate)
	return {
		"line_key": key,
		"item_code": row.item_code,
		"item_name": row.item_name,
		"qty": flt(row.qty),
		"old_rate": flt(row.rate, MONEY),
		"new_rate": flt(new_rate, MONEY),
		"old_amount": flt(old, MONEY),
		"new_amount": flt(new, MONEY),
		"difference": flt(new - old, MONEY),
	}


def _same_price(row, line) -> bool:
	"""The rate at the line's own precision; a service line sent as one lump compares its amount."""
	if flt(row.qty) != flt(line.qty):
		return flt(flt(row.qty) * flt(row.rate), MONEY) == flt(line.amount, MONEY)
	digits = row.precision("rate")
	return flt(row.rate, digits) == flt(line.rate, digits)


def _template_changes(doc) -> list[dict]:
	if not doc.get("sp_calc_template"):
		return []
	today_lines = _priced_today(doc)
	changes = []
	for row in doc.items:
		line = today_lines.get(row.get("sp_line_key"))
		if not line or _same_price(row, line):
			continue
		lump = flt(row.qty) != flt(line.qty)
		changes.append(
			_change(
				row,
				line.line_key,
				row.qty if lump else line.qty,
				line.amount / flt(row.qty) if lump else line.rate,
			)
		)
	return changes


def _hand_changes(doc) -> list[dict]:
	"""A line added by hand follows the price list when its item's price changed after the quote."""
	changes = []
	for row in doc.items:
		if row.get("sp_line_key") or row.get("sp_line_kind") or not row.item_code:
			continue
		price = latest_price(row.item_code, BTC)
		if price and getdate(price.date) > getdate(doc.transaction_date) and flt(price.rate) != flt(row.rate):
			changes.append(_change(row, None, row.qty, price.rate))
	return changes


def differences(doc) -> dict:
	"""What today's prices change on a quote: per line and in total."""
	lines = [*_template_changes(doc), *_hand_changes(doc)]
	return {"lines": lines, "difference": flt(sum(r["difference"] for r in lines), MONEY)}


def _note(doc, lines: list[dict]) -> str:
	parts = []
	if doc.get("valid_till") and getdate(doc.valid_till) < getdate(today()):
		parts.append(_("expired on {0}").format(formatdate(doc.valid_till)))
	if lines:
		names = ", ".join(r["item_name"] or r["item_code"] for r in lines[:NOTE_ITEMS])
		more = len(lines) - NOTE_ITEMS
		names = _("{0} and {1} more").format(names, more) if more > 0 else names
		parts.append(_("prices changed: {0}").format(names))
	return "; ".join(parts)


def check_quote(name: str) -> bool:
	"""Flag one quote when it needs repricing. Returns whether it was flagged."""
	from smart_power.sp_sales.quotation import mark_needs_repricing

	doc = frappe.get_doc(QUOTATION, name)
	case = frappe.db.get_value(CASE, doc.sp_case, ["status", "follow_up_owner"], as_dict=True)
	if not case or case.status in CLOSED_CASES:
		return False
	lines = differences(doc)["lines"]
	note = _note(doc, lines)
	if not note:
		return False
	mark_needs_repricing(name, note)
	send(
		EVENT,
		[doc.get("sp_quote_creator"), case.follow_up_owner],
		QUOTATION,
		name,
		lambda: _("Quote {0} needs repricing: {1}").format(name, _note(doc, lines)),  # per reader (BUG-22)
	)
	return True


def check_quotes() -> None:
	"""Daily: every sent quote still open, one at a time so one bad quote never stops the rest."""
	for name in frappe.get_all(
		QUOTATION,
		{
			"docstatus": 1,
			"sp_status": ("in", CHECKED_STATUSES),
			"sp_is_latest": 1,
			"sp_needs_repricing": 0,
			"sp_old_price_honored": 0,
			"sp_case": ("is", "set"),
		},
		pluck="name",
	):
		frappe.db.savepoint("sp_reprice_check")
		try:
			check_quote(name)
		except Exception:
			frappe.db.rollback(save_point="sp_reprice_check")
			frappe.log_error(title=f"SP-170: could not check quote {name}")


def honor_old_price(doc, reason: str | None = None) -> None:
	"""Approving a flagged version: the rule's level decides. Raises when it may not be approved."""
	hit = next((h for h in evaluate(doc, QUOTE_APPROVE_EVENT) if h.spec.key == OLD_PRICE_RULE), None)
	if not hit:
		return  # the rule is Off
	if hit.level == BLOCK or not can_override():
		frappe.throw(
			_("This version needs repricing ({0}). Make a new version at today's prices.").format(
				doc.get("sp_repricing_note") or _("prices changed")
			)
		)
	if not (reason or "").strip():
		frappe.throw(_("Give the reason for honoring the old price."))
	record_warning(doc, hit, reason.strip())


def can_reprice(doc) -> bool:
	return bool(doc.get("sp_needs_repricing") and doc.get("sp_is_latest") and sees_quote_internals(doc))


def quote_onload(doc, method=None) -> None:
	"""Quotation onload: what the form offers on a version that needs repricing."""
	if not doc.get("sp_case") or not doc.get("sp_needs_repricing"):
		return
	level = effective_level(registry()[OLD_PRICE_RULE], get_rule_setting(OLD_PRICE_RULE))
	doc.set_onload(
		"sp_repricing", {"can_reprice": can_reprice(doc), "can_honor": level == WARN and can_override()}
	)


@frappe.whitelist(methods=["POST"])
def reprice(quotation: str) -> dict:
	"""A new version at today's prices, with the same inputs, overrides, markups and items. The new
	version keeps the difference, per line and in total, for the builder's side panel."""
	from smart_power.sp_sales.quotation import new_version

	source = frappe.get_doc(QUOTATION, quotation)
	source.check_permission("read")
	if not sees_quote_internals(source):
		frappe.throw(_("Only the quote creator and the admin reprice a quote."), frappe.PermissionError)
	if not can_reprice(source):
		frappe.throw(_("Only the latest version that needs repricing can be repriced."))
	change = differences(source)
	doc = frappe.get_doc(QUOTATION, new_version(quotation))
	if doc.get("sp_calc_template"):
		write_lines(
			doc,
			calculate(
				doc.sp_calc_template,
				_json(doc.get("sp_design_inputs")),
				_json(doc.get("sp_calc_overrides")),
				on_date=today(),
				brands=_json(doc.get("sp_brand_order")) if doc.get("sp_brand_order") else None,
				picks=_picks(source),
			),
		)
	rates = {r["item_code"]: r["new_rate"] for r in change["lines"] if not r["line_key"]}
	for row in doc.items:
		if not row.get("sp_line_key") and row.item_code in rates:
			row.rate = rates[row.item_code]
			row.sp_cost = 0  # taken again from today's cost
	doc.sp_reprice_diff = json.dumps(change, ensure_ascii=False)
	doc.save()
	return {"quotation": doc.name, "difference": change["difference"]}
