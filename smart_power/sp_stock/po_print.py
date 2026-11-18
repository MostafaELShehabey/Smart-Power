"""The purchase order PDF (SP-82): what "SP Purchase Order" prints, one dated section per batch.

    po_print(doc) -> {header, batches, total, words, currency, show_prices}

The supplier's prices print only for those who may read them (SP-35): anyone else gets the items,
quantities and dates.
"""

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.permissions import PO_COST_ROLES
from smart_power.sp_core.printing import ar_date, ar_words

PRINT_FORMAT = "SP Purchase Order"


def make_desk_default() -> None:
	"""The purchase order's default print format becomes SP Purchase Order, once, when the current
	one is empty or one of ERPNext's own standard formats. A format the admin built is never replaced."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	current = frappe.get_meta("Purchase Order").default_print_format
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
		"Purchase Order",
		None,
		"default_print_format",
		PRINT_FORMAT,
		"Data",
		for_doctype=True,
		is_system_generated=False,
	)


def sees_prices() -> bool:
	user = frappe.session.user
	return user == "Administrator" or bool(set(PO_COST_ROLES) & set(frappe.get_roles(user)))


def _names(rows) -> dict:
	codes = list({r.item_code for r in rows if r.item_code})
	items = frappe.get_all("Item", {"name": ("in", codes)}, ["name", "sp_name_ar"]) if codes else []
	return {i.name: i.sp_name_ar for i in items if i.sp_name_ar}


def po_print(doc) -> frappe._dict:
	show_prices = sees_prices()
	rows = doc.get("items") or []
	names = _names(rows)
	batches = {}
	for row in sorted(rows, key=lambda r: (r.get("sp_batch_no") or 1, r.idx)):
		batch = batches.setdefault(
			row.get("sp_batch_no") or 1,
			frappe._dict(
				no=row.get("sp_batch_no") or 1, date=ar_date(row.schedule_date), lines=[], total=0.0
			),
		)
		line = frappe._dict(
			no=len(batch.lines) + 1,
			description=names.get(row.item_code) or row.item_name,
			uom=row.uom,
			qty=flt(row.qty),
		)
		if show_prices:
			line.update(rate=flt(row.rate), amount=flt(row.amount))
			batch.total += flt(row.amount)
		batch.lines.append(line)
	total = flt(doc.get("rounded_total") or doc.get("grand_total")) if show_prices else 0
	destination = doc.get("sp_destination_type")
	return frappe._dict(
		header=frappe._dict(
			po_no=doc.get("name"),
			date=ar_date(doc.get("transaction_date")),
			supplier=doc.get("supplier_name") or doc.get("supplier"),
			station=doc.get("sp_station") or "",
			destination=_(destination) if destination else "",
		),
		batches=list(batches.values()),
		total=total,
		words=ar_words(total) if show_prices else "",
		currency=doc.get("currency"),
		show_prices=show_prices,
	)
