"""I3 Stock by location and owner (SP-87): on hand, reserved and available per item, location and
owner, so the supplier's consignment never mixes with company stock.

Two sources, never added together:

    Smart Power   the stock ledger: each warehouse's Bin (main store, showroom store, the sites),
                  reserved = Stock Reservation Entries (Bin.reserved_stock); the value is shown
                  only to those who may see cost
    the supplier  Africa System's consignment containers (SP-91), kept outside the stock ledger:
                  balance, open reservations and what is left, by where each container is kept;
                  they never carry a value, because they are not Smart Power's goods

The story's technical note asked for a `stock_owner` inventory dimension; SP-28 and SP-91 already
keep consignment off the ledger (decision 46, tech plan rule 6), so the owner comes from the
source instead. The report is SP Stock by Owner; its print format is the stock sheet.
"""

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.permissions import can_see_cost
from smart_power.sp_stock.consignment import CONTAINER, EMPTY

SMART_POWER = "Smart Power"
PENNY = 0.0005  # sp-allow-number: below a thousandth of a unit is nothing left


def _warehouses(company: str | None) -> dict:
	filters = {"is_group": 0, "disabled": 0}
	if company:
		filters["company"] = company
	rows = frappe.get_all("Warehouse", filters, ["name", "warehouse_name", "warehouse_type", "company"])
	return {r.name: r for r in rows}


def _location_type(warehouse_type: str | None) -> str:
	"""The warehouse type (SP-28), worded for the reader."""
	labels = {
		"Main": _("Main store"),
		"Showroom": _("Showroom store"),
		"Site": _("Station site"),
		"Transit": _("In transit"),
	}
	return labels.get(warehouse_type, _(warehouse_type) if warehouse_type else "")


def company_rows(filters) -> list[dict]:
	"""Smart Power's own stock: one row per item and warehouse."""
	warehouses = _warehouses(filters.get("company"))
	if filters.get("location"):
		warehouses = {k: v for k, v in warehouses.items() if k == filters.location}
	if not warehouses:
		return []
	conditions = {"warehouse": ("in", list(warehouses))}
	if filters.get("item_code"):
		conditions["item_code"] = filters.item_code
	bins = frappe.get_all(
		"Bin",
		filters=conditions,
		fields=["item_code", "warehouse", "actual_qty", "reserved_stock", "stock_value"],
	)
	names = _item_names({b.item_code for b in bins})
	rows = []
	for b in bins:
		on_hand = flt(b.actual_qty)
		if abs(on_hand) < PENNY and not filters.get("show_zero"):
			continue
		reserved = flt(b.reserved_stock)
		w = warehouses[b.warehouse]
		rows.append(
			{
				"item_code": b.item_code,
				"item_name": names.get(b.item_code),
				"location": b.warehouse,
				"location_type": _location_type(w.warehouse_type),
				"owner": SMART_POWER,
				"owner_kind": "company",
				"on_hand": on_hand,
				"reserved": reserved,
				"available": on_hand - reserved,
				"value": flt(b.stock_value),
			}
		)
	return rows


def consignment_rows(filters) -> list[dict]:
	"""The supplier's goods on consignment: one row per item, supplier and place kept."""
	if filters.get("location"):
		return []  # containers are not in a warehouse
	conditions = {"status": ("!=", EMPTY)} if not filters.get("show_zero") else {}
	if filters.get("company"):
		conditions["company"] = filters.company
	if filters.get("item_code"):
		conditions["item"] = filters.item_code
	boxes = frappe.get_all(
		CONTAINER,
		filters=conditions,
		fields=["item", "item_name", "supplier", "location", "balance_qty", "reserved_qty", "available_qty"],
	)
	suppliers = {
		s.name: s.supplier_name
		for s in frappe.get_all(
			"Supplier", {"name": ("in", list({b.supplier for b in boxes}) or [""])}, ["name", "supplier_name"]
		)
	}
	grouped: dict = {}
	for box in boxes:
		key = (box.item, box.supplier, box.location or "")
		row = grouped.setdefault(
			key,
			{
				"item_code": box.item,
				"item_name": box.item_name,
				"location": box.location or _("Consignment store"),
				"location_type": _("Consignment"),
				"owner": suppliers.get(box.supplier) or box.supplier,
				"owner_kind": "supplier",
				"supplier": box.supplier,
				"on_hand": 0.0,
				"reserved": 0.0,
				"available": 0.0,
				"value": None,
			},
		)
		row["on_hand"] += flt(box.balance_qty)
		row["reserved"] += flt(box.reserved_qty)
		row["available"] += flt(box.available_qty)
	return list(grouped.values())


def _item_names(codes: set) -> dict:
	if not codes:
		return {}
	return {
		r.name: r.item_name
		for r in frappe.get_all("Item", {"name": ("in", list(codes))}, ["name", "item_name"])
	}


def stock_rows(filters: dict | None = None) -> list[dict]:
	"""Company stock and the supplier's consignment, item by item; never summed together."""
	filters = frappe._dict(filters or {})
	rows = []
	if filters.get("owner") in (None, "", "company"):
		rows += company_rows(filters)
	if filters.get("owner") in (None, "", "supplier"):
		rows += consignment_rows(filters)
	rows.sort(key=lambda r: (r["item_code"], r["owner_kind"], r["location"] or ""))
	if not can_see_cost():
		for row in rows:
			row.pop("value", None)
	return rows
