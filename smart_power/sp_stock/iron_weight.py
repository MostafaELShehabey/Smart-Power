"""Chassis iron by scale weight (SP-178; decision 77).

Iron sections are stock items in kg, marked "Weighed at Receipt" on the item. The PO carries the
theoretical weight from its chassis calc (SP-166); the receipt takes the scale weight, confirmed by
the technical office (SP-85). The scale weight is final, above or below the PO (owner,
2026-11-22): at confirmation the weighed line of the PO is set to what was weighed, through
ERPNext's own Update Items, so the line counts as fully received and nothing stays open.

After each supply a Landed Cost Voucher adds transport, unloading and labour, by quantity (kg).
The item's valuation rate is then the cost per kg, and a factory whose iron item is set prices
its next chassis calc with it (chassis_calc.factory_dict).

    is_weighed(item_code)            the item is weighed at receipt
    settle_weighed_lines(receipt)    before the receipt posts: its PO's weighed lines = the scale
    variance(filters)                theoretical vs scale weight per PO, grouped per factory
"""

import json

import frappe
from frappe import _
from frappe.utils import flt

PO, PO_ITEM, RECEIPT_ITEM = "Purchase Order", "Purchase Order Item", "Purchase Receipt Item"
SETTING = "iron_weight_variance_pct"
QTY_DIGITS = 3  # sp-allow-number: kilograms to the gram
PCT = 100  # sp-allow-number: a percentage


def is_weighed(item_code: str | None) -> bool:
	return bool(item_code and frappe.get_cached_value("Item", item_code, "sp_is_weighed"))


def settle_weighed_lines(receipt) -> None:
	"""The scale weight is final: each weighed PO line becomes what was received on it."""
	from erpnext.controllers.accounts_controller import update_child_qty_rate

	weighed: dict[str, dict[str, float]] = {}
	for row in receipt.items:
		if row.get("purchase_order") and row.get("purchase_order_item") and is_weighed(row.item_code):
			lines = weighed.setdefault(row.purchase_order, {})
			lines[row.purchase_order_item] = lines.get(row.purchase_order_item, 0) + flt(row.qty)
	for order, lines in weighed.items():
		po = frappe.get_doc(PO, order)
		changed = False
		rows = []
		for item in po.items:
			qty = flt(item.qty)
			if item.name in lines:
				qty = flt(flt(item.received_qty) + lines[item.name], QTY_DIGITS)
				changed = changed or qty != flt(item.qty)
			rows.append(
				{
					"docname": item.name,
					"item_code": item.item_code,
					"qty": qty,
					"rate": item.rate,
					"uom": item.uom,
					"conversion_factor": item.conversion_factor,
					"schedule_date": str(item.schedule_date),
				}
			)
		if changed:
			update_child_qty_rate(PO, json.dumps(rows), order)


# --- the variance report ----------------------------------------------------------------------


def _factory_of(po) -> str | None:
	"""The PO's chassis calc's factory, else the factory of its supplier or of its iron item."""
	if po.sp_chassis_calc:
		return frappe.db.get_value("SP Chassis Calc", po.sp_chassis_calc, "factory")
	factory = frappe.db.get_value("SP Chassis Factory", {"supplier": po.supplier}, "name")
	if factory:
		return factory
	items = frappe.get_all(PO_ITEM, {"parent": po.name}, pluck="item_code")
	return frappe.db.get_value("SP Chassis Factory", {"iron_item": ("in", items or [""])}, "name")


def _received_kg(order: str) -> float:
	rows = frappe.get_all(
		RECEIPT_ITEM,
		{"purchase_order": order, "docstatus": 1},
		["item_code", "stock_qty"],
	)
	return flt(sum(flt(r.stock_qty) for r in rows if is_weighed(r.item_code)), QTY_DIGITS)


def variance(filters: dict | None = None) -> list[dict]:
	"""Per factory, then its POs: theoretical kg, scale kg, the difference and a warning."""
	filters = frappe._dict(filters or {})
	threshold = flt(frappe.db.get_single_value("Smart Power Settings", SETTING))
	conditions = {"docstatus": 1, "sp_theoretical_weight_kg": (">", 0)}
	if filters.from_date and filters.to_date:
		conditions["transaction_date"] = ("between", [filters.from_date, filters.to_date])
	orders = frappe.get_all(
		PO,
		conditions,
		["name", "transaction_date", "supplier", "sp_chassis_calc", "sp_theoretical_weight_kg"],
		order_by="transaction_date desc, name desc",
	)
	groups: dict[str, list[dict]] = {}
	for po in orders:
		factory = _factory_of(po) or _("No factory")
		if filters.factory and factory != filters.factory:
			continue
		theoretical, actual = flt(po.sp_theoretical_weight_kg), _received_kg(po.name)
		if not actual:
			continue  # nothing weighed yet
		groups.setdefault(factory, []).append(
			_row(po.name, po.transaction_date, theoretical, actual, threshold, 1)
		)
	out = []
	for factory, rows in groups.items():
		theoretical = sum(r["theoretical_kg"] for r in rows)
		actual = sum(r["actual_kg"] for r in rows)
		out.append({**_row(None, None, theoretical, actual, threshold, 0), "factory": factory})
		out += [{**r, "factory": factory} for r in rows]
	return out


def _row(order, day, theoretical: float, actual: float, threshold: float, indent: int) -> dict:
	diff = flt(actual - theoretical, QTY_DIGITS)
	pct = flt(diff / theoretical * PCT, 2) if theoretical else 0  # sp-allow-number: percent digits
	warn = bool(threshold and abs(pct) > threshold)
	return {
		"purchase_order": order,
		"date": day,
		"theoretical_kg": theoretical,
		"actual_kg": actual,
		"variance_kg": diff,
		"variance_pct": pct,
		"warning": _("Above {0}%").format(threshold) if warn else "",
		"indent": indent,
	}
