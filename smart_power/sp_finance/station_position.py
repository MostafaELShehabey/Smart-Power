"""R1 Station financial position (SP-139): today's "ميزان الحركة" sheet, one row per station.

The columns follow the owner's sheet (كشف حساب 2026 > ميزان الحركة) with the story's additions:

    station, customer, contract date, financing, capacity (kW), status
    agreed                                    the contract (station agreed_amount)
    estimated cost                            frozen at the deposit (estimated_cost_snapshot)
    actual cost                               direct + the indirect share (costing.actual_cost)
    owed to suppliers, paid, remaining        the station's share of its suppliers' invoices
                                              and of the payments against them (by line value,
                                              as the supplier ledger splits them, SP-86)
    collected from the customer               confirmed payments (station paid_amount)
    collected - owed to suppliers             the sheet's cash position column
    remaining from the customer               agreed - collected - written off
    expected profit (agreed - estimated), profit (agreed - actual)

Filters: year (of the contract date), financing, status. Admin only: costs and profit.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate

from smart_power.sp_finance.supplier_ledger import INVOICE, MONEY_DIGITS, _split

STATION = "SP Station"
VIEWERS = ("SP Admin", "System Manager")


def check_viewer() -> None:
	if frappe.session.user != "Administrator" and not set(VIEWERS) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin opens the station financial position."), frappe.PermissionError)


def _stations(filters: dict) -> list:
	where = {"status": ("!=", "Cancelled")} if not filters.get("status") else {"status": filters["status"]}
	if filters.get("financing"):
		where["financing_type"] = filters["financing"]
	if filters.get("company"):
		where["company"] = filters["company"]
	rows = frappe.get_all(
		STATION,
		where,
		[
			"name", "customer", "customer_name", "contract_date", "financing_type", "capacity_kw_total",
			"status", "agreed_amount", "paid_amount", "remaining_amount", "project", "company",
			"estimated_cost_snapshot",
		],
		order_by="name asc",
	)  # fmt: skip
	year = filters.get("year")
	if year:
		rows = [r for r in rows if r.contract_date and getdate(r.contract_date).year == int(year)]
	return rows


def _suppliers(companies: set[str]) -> tuple[dict, dict]:
	"""{project: owed} from the suppliers' invoices and {project: still owed} after payments."""
	if not companies:
		return {}, {}
	lines = frappe.get_all(
		"GL Entry",
		{"party_type": "Supplier", "company": ("in", list(companies)), "is_cancelled": 0},
		[
			"voucher_type",
			"voucher_no",
			"against_voucher_type",
			"against_voucher",
			"debit",
			"credit",
			"project",
		],
	)
	billed = _split([line for line in lines if line.voucher_type == INVOICE])
	left = _split(lines)
	return billed, left


def rows(filters: dict | None = None) -> list[dict]:
	from smart_power.sp_stations.costing import actual_cost

	filters = frappe._dict(filters or {})
	stations = _stations(filters)
	billed, left = _suppliers({s.company for s in stations})
	labels = dict(
		frappe.get_all(
			"SP List Value",
			{"name": ("in", list({s.financing_type for s in stations if s.financing_type}) or [""])},
			["name", "value_ar"],
			as_list=True,
		)
	)
	out = []
	for s in stations:
		agreed = flt(s.agreed_amount)
		estimated = flt(json.loads(s.estimated_cost_snapshot or "{}").get("total_cost"))
		actual = actual_cost(s.name)["total"]
		owed = flt(billed.get(s.project), MONEY_DIGITS)
		remaining_suppliers = flt(left.get(s.project), MONEY_DIGITS)
		collected = flt(s.paid_amount)
		out.append(
			{
				"station": s.name,
				"customer_name": s.customer_name or s.customer,
				"contract_date": s.contract_date,
				"financing": labels.get(s.financing_type) or s.financing_type,
				"capacity_kw": flt(s.capacity_kw_total),
				"status": _(s.status),
				"agreed": agreed,
				"estimated_cost": estimated,
				"actual_cost": actual,
				"owed_to_suppliers": owed,
				"paid_to_suppliers": flt(owed - remaining_suppliers, MONEY_DIGITS),
				"remaining_to_suppliers": remaining_suppliers,
				"collected": collected,
				"cash_position": collected - owed,
				"remaining_from_customer": flt(s.remaining_amount),
				"expected_profit": agreed - estimated,
				"profit": agreed - actual,
			}
		)
	return out
