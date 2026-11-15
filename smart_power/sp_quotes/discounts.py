"""Discounts on a quote (SP-68, decisions 29, 47, 66, 67 and 77).

Two kinds of discount:
- a line's markup, changed by the quote creator with no limit (SP-55's set_line_override: logged
  in SP Edit Reason Log, refused on a locked line);
- a discount on the quote total or on one section (Energy, Submersible), and the customer's
  last-minute ask (العشم), kept in the quote's Discounts table. Their sum is the quote's
  discount on the net total, so the totals, the margin and the PDF follow.

    give_discount(quotation, percent | amount, applies_to, kind, note)   the F4 dialog

There is no approval gate (decision 67): a discount above the giver's limit (Smart Power
Settings) is saved and listed for the admin by the discount rules; the admin is told of every
discount; a sent version is never changed, so the discount makes a new version. After a
discount the margin is checked against its offer type's range, as a warning only.
A single line is never discounted on its own: a locked line (BTC price, chassis iron) refuses a
line discount, and the Discounts table only knows the quote total and its sections.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from smart_power.rules import evaluate, record_warning
from smart_power.rules.sales import QUOTE_SEND_EVENT

QUOTATION, CASE = "Quotation", "SP Case"
DISCOUNT, LAST_MINUTE = "Discount", "Last-minute ask"
KINDS = (DISCOUNT, LAST_MINUTE)
ADMIN_ROLE = "SP Admin"
DISCOUNT_RULES = ("discount_followup_max", "discount_creator_max")
PCT = 100


# --- on save (Quotation validate) -------------------------------------------------------------


def sections(doc) -> dict[str, float]:
	"""Each section of the quote and its total before discounts."""
	out = {}
	for row in doc.get("items") or []:
		if row.get("sp_line_section"):
			out[row.sp_line_section] = out.get(row.sp_line_section, 0.0) + flt(row.amount)
	return out


def apply_discounts(doc) -> None:
	"""The Discounts table becomes the quote's discount on its net total."""
	rows = doc.get("sp_discounts") or []
	if not rows:
		before = doc.get_doc_before_save() if not doc.is_new() else None
		if before and before.get("sp_discounts"):  # the last discount row was removed
			doc.discount_amount = 0
			doc.calculate_taxes_and_totals()
		return
	totals = sections(doc)
	quote_total = sum(flt(r.amount) for r in doc.items)
	for row in rows:
		if row.kind not in KINDS:
			frappe.throw(_("Unknown discount kind {0}.").format(frappe.bold(row.kind)))
		base = quote_total
		if row.applies_to:
			if row.applies_to not in totals:
				frappe.throw(
					_("{0} is not a section of this quote. Discount a section or the quote total.").format(
						frappe.bold(row.applies_to)
					)
				)
			base = totals[row.applies_to]
		if flt(row.percent):
			row.amount = flt(base * flt(row.percent) / PCT, row.precision("amount"))
		if flt(row.amount) <= 0:
			frappe.throw(_("Row {0}: give a discount above zero.").format(row.idx))
		if flt(row.amount) > base:
			frappe.throw(
				_("Row {0}: the discount {1} is more than the total it applies to ({2}).").format(
					row.idx,
					frappe.format(row.amount, "Currency"),
					frappe.format(base, "Currency"),
				)
			)
		row.given_by = row.given_by or frappe.session.user
		row.given_on = row.given_on or now_datetime()
	discount = sum(flt(r.amount) for r in rows)
	if discount > quote_total:
		frappe.throw(_("The discounts are more than the quote total."))
	doc.apply_discount_on = "Net Total"
	doc.additional_discount_percentage = 0
	doc.discount_amount = discount
	doc.calculate_taxes_and_totals()


def check_locked_lines(doc, method=None) -> None:
	"""Quotation before_validate: a locked line (BTC price, chassis iron) is never discounted on
	its own. Checked on what the user entered, before ERPNext recalculates the line: a line
	discount, or a price cut by hand. A recalculation from the template writes new rows, so it
	passes."""
	if not doc.get("sp_case"):
		return
	before = doc.get_doc_before_save() if not doc.is_new() else None
	old_rates = {r.name: flt(r.rate) for r in (before.items if before else [])}
	for row in doc.get("items") or []:
		if not row.get("sp_lock_markup"):
			continue
		cut = row.name in old_rates and flt(row.rate) < old_rates[row.name]
		if flt(row.get("discount_percentage")) or cut:
			frappe.throw(
				_(
					"Row {0} ({1}) is locked: it cannot be discounted on its own. Discount its section or the quote total."
				).format(row.idx, row.item_name or row.item_code),
				title=_("Locked line"),
			)


# --- the F4 dialog ------------------------------------------------------------------------------


def _check_can_discount(doc):
	from smart_power.sp_sales.quotation import _can_approve

	if not doc.get("sp_case"):
		frappe.throw(_("Only a quote linked to a case is discounted here."))
	case = frappe.get_doc(CASE, doc.sp_case)
	if case.status in ("Won", "Lost"):
		frappe.throw(
			_("Case {0} is {1}; its quotes are not discounted any more.").format(case.name, _(case.status))
		)
	if not _can_approve(case):
		frappe.throw(
			_("Only the case's follow-up owner, its quote creator or the admin can give a discount."),
			frappe.PermissionError,
		)
	if doc.docstatus.is_cancelled():
		frappe.throw(_("A cancelled quote cannot be discounted."))
	return case


@frappe.whitelist()
def discount_options(quotation: str) -> dict:
	"""What the F4 dialog offers: the sections and totals at sale price, and the giver's limit."""
	from smart_power.sp_core.services.settings import get_value

	doc = frappe.get_doc(QUOTATION, quotation)
	_check_can_discount(doc)
	roles = set(frappe.get_roles())
	limit = None
	if "SP Quote Creator" in roles:
		limit = get_value("creator_discount_max_pct")
	elif "SP Customer Followup" in roles:
		limit = get_value("followup_discount_max_pct")
	return {
		"quotation": doc.name,
		"is_sent": bool(doc.docstatus.is_submitted()),
		"currency": doc.currency,
		"total": sum(flt(r.amount) for r in doc.items),
		"grand_total": doc.rounded_total or doc.grand_total,
		"sections": [{"section": k, "total": v} for k, v in sections(doc).items()],
		"discounts": [
			{
				"kind": r.kind,
				"applies_to": r.applies_to,
				"percent": r.percent,
				"amount": r.amount,
				"note": r.note,
			}
			for r in doc.get("sp_discounts") or []
		],
		"limit_pct": flt(limit) or None,
	}


@frappe.whitelist(methods=["POST"])
def give_discount(
	quotation: str,
	percent: float | None = None,
	amount: float | None = None,
	applies_to: str | None = None,
	kind: str = DISCOUNT,
	note: str | None = None,
) -> dict:
	"""Give a discount on the quote total or a section (F4). A sent version gets a new version."""
	from smart_power.sp_sales.quotation import new_version

	doc = frappe.get_doc(QUOTATION, quotation)
	case = _check_can_discount(doc)
	if not flt(percent) and not flt(amount):
		frappe.throw(_("Give a percent or an amount."))
	made_version = False
	if doc.docstatus.is_submitted():
		doc = frappe.get_doc(QUOTATION, new_version(doc.name))
		made_version = True
	doc.append(
		"sp_discounts",
		{
			"kind": kind,
			"applies_to": applies_to or None,
			"percent": flt(percent) or None,
			"amount": None if flt(percent) else flt(amount),
			"note": note,
		},
	)
	# no approval gate: the note is the reason the discount rules keep with their warning
	doc.flags.sp_rule_reasons = dict.fromkeys(DISCOUNT_RULES, note or _("Discount given"))
	doc.save()
	given = doc.sp_discounts[-1]
	_tell_admins(doc, case, given)
	return {
		"quotation": doc.name,
		"new_version": made_version,
		"amount": given.amount,
		"total": doc.rounded_total or doc.grand_total,
		"warnings": check_margin(doc),
	}


def _tell_admins(doc, case, row) -> None:
	from smart_power.notify import send
	from smart_power.sp_sales.quote_request import _users_with

	admins = sorted(set(_users_with(ADMIN_ROLE)) - {frappe.session.user})
	if not admins:
		return
	where = row.applies_to or _("the quote total")
	send(
		"discount_given",
		admins,
		CASE,
		case.name,
		_("{0} gave {1} off {2} on quote {3} ({4})").format(
			frappe.utils.get_fullname(frappe.session.user),
			frappe.format(row.amount, {"fieldtype": "Currency", "options": doc.currency}),
			where,
			doc.name,
			case.customer_name or case.customer,
		),
		from_user=frappe.session.user,
	)


def check_margin(doc) -> list[str]:
	"""After a discount the margin is checked against its offer type's range: a warning only."""
	messages = []
	for hit in evaluate(doc, QUOTE_SEND_EVENT):
		record_warning(doc, hit)
		messages.append(hit.finding.message)
	return messages
