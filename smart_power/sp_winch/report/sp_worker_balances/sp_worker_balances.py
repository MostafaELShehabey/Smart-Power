"""Worker balances (SP-181): what each winch and Jumbo crew member still owes on his advances, his
installment, and how and when he last repaid. One row per worker; the total row sums them."""

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.sp_winch.crew_pay import ADVANCE, REPAYMENT

NARROW, MONEY, NAME = 110, 125, 180  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	conditions = {"docstatus": 1}
	if filters.vehicle:
		conditions["vehicle"] = filters.vehicle
	if not filters.include_repaid:
		conditions["status"] = "Open"
	advances = frappe.get_all(
		ADVANCE,
		filters=conditions,
		fields=[
			"name",
			"employee",
			"employee_name",
			"daily_worker",
			"vehicle",
			"amount",
			"repaid_amount",
			"outstanding_amount",
			"installment_amount",
			"status",
		],
		order_by="employee_name asc, work_date asc",
	)
	rows: dict = {}
	for a in advances:
		row = rows.setdefault(
			a.employee,
			{
				"employee": a.employee,
				"employee_name": a.employee_name,
				"daily_worker": a.daily_worker,
				"vehicle": a.vehicle,
				"advances": 0,
				"amount": 0.0,
				"repaid": 0.0,
				"outstanding": 0.0,
				"installment": 0.0,
			},
		)
		row["advances"] += 1
		row["amount"] += flt(a.amount)
		row["repaid"] += flt(a.repaid_amount)
		row["outstanding"] += flt(a.outstanding_amount)
		if a.status == "Open":
			row["installment"] += flt(a.installment_amount)
	last = _last_repayments([a.name for a in advances])
	for a in advances:
		paid = last.get(a.name)
		row = rows[a.employee]
		if paid and (not row.get("last_repaid") or paid.repayment_date > row["last_repaid"]):
			row.update({"last_repaid": paid.repayment_date, "last_kind": _(paid.kind)})
	return columns(), list(rows.values())


def _last_repayments(advances: list[str]) -> dict:
	if not advances:
		return {}
	rows = frappe.get_all(
		REPAYMENT,
		filters={"parent": ("in", advances), "parenttype": ADVANCE},
		fields=["parent", "repayment_date", "kind"],
		order_by="repayment_date asc",
	)
	return {r.parent: r for r in rows}


def columns() -> list[dict]:
	money = {"fieldtype": "Currency", "width": MONEY}
	return [
		{
			"fieldname": "employee",
			"label": _("Worker"),
			"fieldtype": "Link",
			"options": "Employee",
			"width": NARROW,
		},
		{"fieldname": "employee_name", "label": _("Worker Name"), "fieldtype": "Data", "width": NAME},
		{"fieldname": "daily_worker", "label": _("Daily Worker"), "fieldtype": "Check", "width": NARROW},
		{
			"fieldname": "vehicle",
			"label": _("Vehicle"),
			"fieldtype": "Link",
			"options": "Vehicle",
			"width": NARROW,
		},
		{"fieldname": "advances", "label": _("Advances"), "fieldtype": "Int", "width": NARROW},
		{"fieldname": "amount", "label": _("Given"), **money},
		{"fieldname": "repaid", "label": _("Repaid"), **money},
		{"fieldname": "outstanding", "label": _("Outstanding"), **money},
		{"fieldname": "installment", "label": _("Installment"), **money},
		{"fieldname": "last_repaid", "label": _("Last Repaid"), "fieldtype": "Date", "width": NARROW},
		{"fieldname": "last_kind", "label": _("How"), "fieldtype": "Data", "width": NARROW},
	]
