"""What the Arabic customer quote PDF prints (SP-62), gathered in one place.

    quote_print(doc) -> {header, lines, totals, options, schedule, loads, pumps, stamp}

The print format "SP Quotation" only lays this out. Nothing here reads a cost, a profit or a
margin: the customer's PDF never shows them (a test checks the template, too).

- Lines: hidden lines are left out and lines of one merge group print as one line ("مقطوعية")
  with their combined total. Both come from SP-58's line fields when they exist.
- Options: when the case has more than one option (A/B/C), each option's latest version is
  printed side by side, with its lines and total.
"""

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.utils import flt

from smart_power.sp_core.printing import ar_date, ar_words, embed_image

CASE = "SP Case"
LUMP_SUM = "مقطوعية"
CANCELLED = DocStatus.cancelled()


def _arabic_names(item_codes) -> dict:
	codes = list({c for c in item_codes if c})
	if not codes:
		return {}
	return {
		r.name: r.sp_name_ar or r.item_name
		for r in frappe.get_all(
			"Item", filters={"name": ("in", codes)}, fields=["name", "sp_name_ar", "item_name"]
		)
	}


def print_lines(rows, names=None) -> list[dict]:
	"""The lines the customer sees: hidden lines out, merge groups collapsed, numbered."""
	names = names if names is not None else _arabic_names(r.get("item_code") for r in rows)
	lines, groups = [], {}
	for row in rows:
		if row.get("sp_is_hidden"):
			continue
		group = (row.get("sp_merge_group") or "").strip()
		if group:
			if group not in groups:
				groups[group] = {"description": group, "uom": LUMP_SUM, "qty": 1, "rate": 0.0, "amount": 0.0}
				lines.append(groups[group])
			groups[group]["amount"] += flt(row.get("amount"))
			groups[group]["rate"] = groups[group]["amount"]
			continue
		lines.append(
			{
				"description": names.get(row.get("item_code"))
				or row.get("item_name")
				or row.get("description"),
				"uom": row.get("uom") or row.get("stock_uom"),
				"qty": flt(row.get("qty")),
				"rate": flt(row.get("rate")),
				"amount": flt(row.get("amount")),
			}
		)
	for number, line in enumerate(lines, start=1):
		line["no"] = number
	return lines


def _case(doc) -> frappe._dict:
	if not doc.get("sp_case"):
		return frappe._dict()
	return frappe.get_cached_doc(CASE, doc.sp_case)


def _system_type(case) -> str:
	rows = case.get("system_types") or []
	if not rows:
		return ""
	return frappe.db.get_value("SP List Value", rows[0].system_type, "value_ar") or rows[0].system_type


def _options(doc) -> list[dict]:
	"""Each option's latest version on the case, when there is more than one option."""
	if not doc.get("sp_case"):
		return []
	quotes = frappe.get_all(
		"Quotation",
		filters={"sp_case": doc.sp_case, "docstatus": ("<", CANCELLED)},
		fields=["name", "sp_option_label", "sp_version", "grand_total", "rounded_total", "currency"],
		order_by="sp_version desc",
	)
	latest = {}
	for q in quotes:
		latest.setdefault(q.sp_option_label or "A", q)
	if len(latest) <= 1:
		return []
	options = []
	for label in sorted(latest):
		q = latest[label]
		rows = frappe.get_all(
			"Quotation Item",
			filters={"parent": q.name, "parenttype": "Quotation"},
			fields=["*"],
			order_by="idx asc",
		)
		options.append(
			{
				"label": label,
				"name": q.name,
				"version": q.sp_version,
				"is_this": q.name == doc.name,
				"lines": print_lines(rows),
				"total": flt(q.rounded_total or q.grand_total),
				"currency": q.currency,
			}
		)
	return options


def _pumps(doc, names) -> list[dict]:
	"""Pump data for the technical annex: the stored specs of the pumps and motors on the quote."""
	codes = [r.item_code for r in doc.get("items") or [] if r.get("item_code")]
	if not codes:
		return []
	specs = frappe.get_all(
		"Item",
		filters={"name": ("in", codes), "sp_hp": (">", 0)},
		fields=["name", "sp_hp", "sp_head_m", "sp_flow_m3h"],
	)
	return [
		{
			"description": names.get(s.name) or s.name,
			"hp": s.sp_hp,
			"head_m": s.sp_head_m,
			"flow_m3h": s.sp_flow_m3h,
		}
		for s in specs
	]


def quote_print(doc) -> frappe._dict:
	"""Everything the quote PDF prints for one quote version."""
	case = _case(doc)
	rows = doc.get("items") or []
	names = _arabic_names(r.get("item_code") for r in rows)
	total = flt(doc.get("rounded_total") or doc.get("grand_total"))
	from smart_power.sp_core.services.company import get_company_settings

	stamp = get_company_settings().stamp_image
	return frappe._dict(
		header=frappe._dict(
			quote_no=doc.get("name"),
			version=doc.get("sp_version"),
			option=doc.get("sp_option_label") or "A",
			date=ar_date(doc.get("transaction_date")),
			valid_till=ar_date(doc.get("valid_till")),
			customer=doc.get("customer_name") or doc.get("party_name"),
			site=case.get("location_text") or "",
			system_type=_system_type(case) if case else "",
			case=doc.get("sp_case"),
		),
		lines=print_lines(rows, names),
		optional=[
			{
				"description": _arabic_names([r.item_code]).get(r.item_code) or r.item_name or r.item_code,
				"note": r.note,
				"qty": flt(r.qty),
				"amount": flt(r.amount),
			}
			for r in doc.get("sp_optional_lines") or []
		],
		totals=frappe._dict(
			subtotal=flt(doc.get("total")),
			discount=flt(doc.get("discount_amount")),
			# SP-68: each discount on its own line; the last-minute ask (العشم) as its own line
			discounts=[
				{
					"label": _("Last-minute discount")
					if r.kind == "Last-minute ask"
					else (_("Discount on {0}").format(r.applies_to) if r.applies_to else _("Discount")),
					"amount": flt(r.amount),
				}
				for r in doc.get("sp_discounts") or []
			],
			taxes=flt(doc.get("total_taxes_and_charges")),
			total=total,
			words=ar_words(total),
			currency=doc.get("currency"),
		),
		options=_options(doc),
		schedule=[
			{
				"due_date": ar_date(r.due_date),
				"portion": flt(r.invoice_portion),
				"amount": flt(r.payment_amount),
				"description": r.get("description") or "",
			}
			for r in doc.get("payment_schedule") or []
		],
		loads=[
			{
				"device": r.device,
				"qty": flt(r.qty),
				"watts": flt(r.watts),
				"day_hours": flt(r.day_hours),
				"night_hours": flt(r.night_hours),
			}
			for r in case.get("loads") or []
		],
		pumps=_pumps(doc, names),
		stamp=embed_image(stamp) if stamp else "",
		labels=frappe._dict(lump_sum=_(LUMP_SUM)),
	)


PRINT_FORMAT = "SP Quotation"


def seed_default_print_format() -> None:
	"""Smart Power Settings > Default Quote Print Format: SP Quotation, once, if empty (sending a
	quote, SP-61, prints it). The desk's own default for Quotation stays the admin's choice."""
	settings = "Smart Power Settings"
	if not frappe.db.get_single_value(settings, "default_quote_print_format"):
		frappe.db.set_single_value(settings, "default_quote_print_format", PRINT_FORMAT)


def make_desk_default() -> None:
	"""Quotation's default print format in the desk becomes SP Quotation, once, when the current
	one is empty or one of ERPNext's own standard formats (decided by the user, 2026-11-14). A
	format the admin built is never replaced, and the setting stays the admin's to change."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	current = frappe.get_meta("Quotation").default_print_format
	if current == PRINT_FORMAT:
		return
	if current:
		standard, module = frappe.db.get_value("Print Format", current, ["standard", "module"]) or (
			None,
			None,
		)
		if standard != "Yes" or (module or "").startswith("SP "):
			return  # the admin's own format
	make_property_setter(
		"Quotation",
		None,
		"default_print_format",
		PRINT_FORMAT,
		"Data",
		for_doctype=True,
		is_system_generated=False,
	)
