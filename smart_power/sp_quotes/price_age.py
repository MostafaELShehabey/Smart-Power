"""Stale prices on quotes (SP-63): a clock on each stale line, a reason or a stop when sending.

- Each line of a draft keeps its price age (the older of its sale price and its cost, SP-30) and
  status: fresh, aging (amber), stale (red), no limit, no price. The quote form shows a clock on
  the stale and aging lines.
- When a quote is sent, its stale lines are checked against their price category's level (X6):
  Off is no check; Warn asks the sender for a reason, which is listed for the admin (RV2);
  Block stops the send, naming the stale items, until their prices are updated.
- The rule (quote_price_age, rules.sales) can be switched off as a whole in the rules screen.
"""

import frappe
from frappe import _
from frappe.utils import cint, today

from smart_power.sp_stock.prices import STALE, get_price

CATEGORY = "SP Price Category"
OFF, WARN, BLOCK = "Off", "Warn", "Block"
TIER_FIELD = "sp_tier"


class StalePriceBlocked(frappe.ValidationError):
	"""A stale price whose category is at Block: the quote is not sent."""


class StalePriceReasonRequired(frappe.ValidationError):
	"""A stale price whose category is at Warn: the send needs a reason."""


def _tier(doc) -> str:
	customer = doc.get("party_name") if doc.get("quotation_to", "Customer") == "Customer" else None
	return (customer and frappe.db.get_value("Customer", customer, TIER_FIELD)) or "Individual"


def set_line_ages(doc, method=None) -> None:
	"""Quotation validate: each draft line's price age and status (a sent version is frozen)."""
	if not doc.get("sp_case") or cint(doc.docstatus) != 0:
		return
	tier, on_date = _tier(doc), doc.get("transaction_date") or today()
	for row in doc.items:
		if not row.item_code:
			continue
		price = get_price(row.item_code, tier, on_date)
		row.sp_price_age_days = price.age_days
		row.sp_price_status = price.age_status


def stale_lines(doc, on_date=None) -> list[dict]:
	"""The lines whose price is stale on the send date, with their category's level (not Off)."""
	tier, on_date = _tier(doc), on_date or today()
	out, seen = [], set()
	for row in doc.items:
		if not row.item_code or row.item_code in seen:
			continue
		price = get_price(row.item_code, tier, on_date)
		if price.age_status != STALE:
			continue
		level, max_days = (
			frappe.get_cached_value(CATEGORY, price.category, ["rule_level", "max_age_days"])
			if price.category
			else (WARN, None)
		)
		if (level or WARN) == OFF:
			continue
		seen.add(row.item_code)
		out.append(
			{
				"item_code": row.item_code,
				"item_name": row.item_name or row.item_code,
				"age_days": price.age_days,
				"max_days": max_days,
				"level": level or WARN,
			}
		)
	return out


def describe(lines: list[dict]) -> str:
	return ", ".join(
		_("{0} ({1} days, limit {2})").format(r["item_name"], r["age_days"], r["max_days"]) for r in lines
	)


def check_before_send(doc, hit, reason: str | None) -> None:
	"""Stop a send with a stale price at Block; ask for a reason at Warn."""
	if not hit:
		return
	lines = hit.finding.data.get("lines") or []
	blocked = [r for r in lines if r["level"] == BLOCK]
	if blocked:
		frappe.throw(
			_("Update these prices before sending: {0}").format(describe(blocked)),
			StalePriceBlocked,
			title=_("Stale prices"),
		)
	if lines and not (reason or "").strip():
		frappe.throw(
			_("Old prices on this quote: {0}. Give a reason to send it anyway.").format(describe(lines)),
			StalePriceReasonRequired,
			title=_("Stale prices"),
		)


def send_check(doc) -> dict:
	"""For the send dialog: {"block": [...], "warn": [...]} stale lines by level."""
	from smart_power.rules.sales import price_age_hit

	hit = price_age_hit(doc)
	lines = hit.finding.data.get("lines") if hit else []
	return {
		"block": [r for r in lines if r["level"] == BLOCK],
		"warn": [r for r in lines if r["level"] == WARN],
	}
