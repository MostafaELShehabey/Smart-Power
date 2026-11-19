"""W2 month grid (SP-111): the vehicle's month, laid out like the owner's winch sheet.

One row per entry, in the sheet's column order (حركة الونش 17-11-2026): date, item, worker days,
agreed, paid by the customer, wage expenses, vehicle running expenses, handed in, the running
balance with the operator, and Smart Power's own jobs and expenses apart. Money the office
collected on this vehicle's jobs (SP-112) is listed on its day, but it never reached the operator,
so it leaves the balance alone.

    running balance = cash received - handed in (confirmed, SP-117) - what custody paid

which is the operator's transit and custody together in the books. The month ends, as the sheet
does, with revenue, costs, net, the collection rate, what is still uncollected and the discounts.

    month_rows(vehicle, year, month)   the rows, with the opening balance first
    month_totals(vehicle, year, month) the sheet's closing block, for W2 and the year summary
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, get_first_day, getdate

from smart_power.sp_winch.bookings import FOR_OUTSIDE, _job_label
from smart_power.sp_winch.field_entry import (
	DEPOSIT,
	ENTRY,
	EXPENSE,
	FROM_CUSTODY,
	JOB,
	MONEY,
	TRANSFER,
	WORKER_WAGE,
	_code,
)
from smart_power.sp_winch.receipts import ALLOCATION, RECEIPT

CONFIRMED = "Confirmed"
FIELDS = (
	"name",
	"entry_kind",
	"work_date",
	"job_type",
	"for_kind",
	"station",
	"internal_center",
	"customer_name",
	"place",
	"days",
	"agreed_amount",
	"received_now",
	"expense_type",
	"paid_from",
	"worker",
	"money_kind",
	"related_job",
	"amount",
	"transfer",
	"note",
)


def _span(year: int, month: int):
	start = get_first_day(getdate(f"{int(year)}-{int(month):02d}-01"))
	return start, add_to_date(add_to_date(start, months=1), days=-1)


def _entries(vehicle: str, filters: dict) -> list:
	return frappe.get_all(
		ENTRY,
		filters={"vehicle": vehicle, **filters},
		fields=list(FIELDS),
		order_by="work_date asc, creation asc",
	)


def _office_receipts(vehicle: str, start, end) -> list:
	"""What the office collected on this vehicle's jobs in the month (SP-112), by receipt day."""
	rows = frappe.get_all(
		ALLOCATION,
		filters={"vehicle": vehicle, "parenttype": RECEIPT},
		fields=["parent", "job", "amount", "discount", "discount_reason"],
	)
	if not rows:
		return []
	receipts = {
		r.name: r
		for r in frappe.get_all(
			RECEIPT,
			filters={"name": ("in", {r.parent for r in rows}), "work_date": ("between", [start, end])},
			fields=["name", "work_date", "customer_name"],
		)
	}
	return [
		frappe._dict(
			{
				**row,
				"work_date": receipts[row.parent].work_date,
				"customer": receipts[row.parent].customer_name,
			}
		)
		for row in rows
		if row.parent in receipts
	]


def _transfers(entries: list) -> dict:
	names = [e.transfer for e in entries if e.transfer]
	if not names:
		return {}
	rows = frappe.get_all(TRANSFER, {"name": ("in", names)}, ["name", "amount", "status"])
	return {r.name: r for r in rows}


def _worker_names(entries: list) -> dict:
	names = [e.worker for e in entries if e.worker]
	if not names:
		return {}
	rows = frappe.get_all("Employee", {"name": ("in", names)}, ["name", "employee_name"])
	return {r.name: r.employee_name for r in rows}


def _item(entry, workers: dict) -> str:
	if entry.entry_kind == JOB:
		who = entry.customer_name or entry.station or entry.internal_center or ""
		return " · ".join(part for part in (_job_label(entry.job_type), who, entry.place) if part)
	if entry.entry_kind == EXPENSE:
		worker = workers.get(entry.worker)
		label = _job_label(entry.expense_type)
		return _("{0} for {1}").format(label, worker) if worker else label
	if entry.money_kind == DEPOSIT:
		return _("Handed in")
	return _("Received on {0}").format(entry.related_job or "")


def _row(entry, transfers: dict, workers: dict) -> dict:
	"""One sheet line, and in cash_moved what it did to the operator's pocket."""
	row = {
		"work_date": entry.work_date,
		"entry": entry.name,
		"item": _item(entry, workers),
		"days": flt(entry.days) or None,
		"note": entry.note,
	}
	internal = entry.entry_kind == JOB and entry.for_kind != FOR_OUTSIDE
	if internal:
		row["sp_jobs"] = flt(entry.agreed_amount)
	elif entry.entry_kind == JOB:
		row["agreed"] = flt(entry.agreed_amount)
		row["paid"] = flt(entry.received_now) or None
	elif entry.entry_kind == MONEY and entry.money_kind != DEPOSIT:
		row["paid"] = flt(entry.amount)
	if entry.entry_kind == EXPENSE:
		if entry.paid_from != FROM_CUSTODY:  # the shop paid it, not the operator (SP-108)
			row["sp_expenses"] = -flt(entry.amount)
		elif _code(entry.expense_type) == WORKER_WAGE:
			row["wages"] = -flt(entry.amount)
		else:
			row["running"] = -flt(entry.amount)
	transfer = transfers.get(entry.transfer)
	if entry.entry_kind == MONEY and entry.money_kind == DEPOSIT:
		row["deposited"] = -flt(entry.amount)
	elif transfer:  # money received by a method other than cash leaves at once (SP-108)
		row["deposited"] = -flt(transfer.amount)
	confirmed = bool(transfer) and transfer.status == CONFIRMED
	if row.get("deposited") and not confirmed:
		waiting = _("Transfer waiting for the admin")
		row["note"] = f"{row['note']} · {waiting}" if row["note"] else waiting
	row["cash_moved"] = (
		flt(row.get("paid"))
		+ flt(row.get("wages"))
		+ flt(row.get("running"))
		+ (flt(row.get("deposited")) if confirmed else 0.0)
	)
	return row


def _receipt_row(row) -> dict:
	discount_only = not flt(row.amount) and flt(row.discount)
	return {
		"work_date": row.work_date,
		"entry": row.job,
		"item": _("Collected at the office ({0}): {1}").format(row.parent, row.customer or ""),
		"paid": flt(row.amount) or None,
		"discount": flt(row.discount) or None,
		"cash_moved": 0.0,  # the office received it: nothing reached the operator
		"note": _("Discount: {0}").format(row.discount_reason or "") if discount_only else None,
	}


def opening_balance(vehicle: str, before) -> float:
	"""The operator's cash at the month's start: every earlier entry, by the same arithmetic."""
	entries = _entries(vehicle, {"work_date": ("<", before)})
	transfers = _transfers(entries)
	return sum(_row(entry, transfers, {})["cash_moved"] for entry in entries)


def month_rows(vehicle: str, year: int, month: int) -> list[dict]:
	start, end = _span(year, month)
	entries = _entries(vehicle, {"work_date": ("between", [start, end])})
	transfers, workers = _transfers(entries), _worker_names(entries)
	rows = [_row(entry, transfers, workers) for entry in entries]
	rows += [_receipt_row(row) for row in _office_receipts(vehicle, start, end)]
	rows.sort(key=lambda r: (getdate(r["work_date"]), r.get("entry") or ""))
	balance = opening_balance(vehicle, start)
	rows.insert(0, {"work_date": start, "item": _("Balance from the month before"), "balance": balance})
	for row in rows[1:]:
		balance += row.pop("cash_moved", 0.0)
		row["balance"] = balance
	return rows


def month_totals(vehicle: str, year: int, month: int) -> dict:
	"""The sheet's closing block; the year summary shows one of these per month (SP-111)."""
	start, end = _span(year, month)
	rows = month_rows(vehicle, year, month)
	totals = {
		field: sum(flt(r.get(field)) for r in rows)
		for field in ("agreed", "paid", "wages", "running", "deposited", "sp_jobs", "sp_expenses", "discount")
	}
	uncollected = sum(
		flt(r.outstanding_amount)
		for r in frappe.get_all(
			ENTRY,
			{
				"vehicle": vehicle,
				"work_date": ("between", [start, end]),
				"entry_kind": JOB,
				"for_kind": FOR_OUTSIDE,
			},
			["outstanding_amount"],
		)
	)
	revenue = totals["paid"] + totals["sp_jobs"]
	costs = totals["wages"] + totals["running"] + totals["sp_expenses"]
	return {
		**totals,
		"balance": rows[-1]["balance"] if rows else 0.0,
		"revenue": revenue,
		"costs": costs,
		"net": revenue + costs,
		"collection_rate": (totals["paid"] / totals["agreed"]) if totals["agreed"] else None,
		"uncollected": uncollected,
	}
