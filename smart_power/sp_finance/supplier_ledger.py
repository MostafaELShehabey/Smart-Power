"""The supplier's ledger (SP-86, P5): every invoice, consignment withdrawal and payment with the
running balance, what each station owes, and what falls due.

The ledger reads the supplier's General Ledger lines. A station is its Project (SP-27). A payment
counts against the stations of the invoices it pays, and an invoice for several stations is shared
by the value of its lines, so the station split always adds up to the balance.

    supplier_ledger(supplier, ...)   the lines, the balance, the station split and the open invoices
    dues_this_week(company)          what falls due within a week, overdue included
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

from smart_power.sp_finance.supplier_payment import INVOICE, default_company, open_invoices

VIEWERS = ("SP Supplier Accounts", "SP Accountant", "SP Admin", "System Manager")
SUPPLIER = "Supplier"
WEEK = 7  # sp-allow-number: the story's week
MONEY_DIGITS = 2  # sp-allow-number: currency precision
INVOICE_KIND, WITHDRAWAL, PAYMENT, OTHER = "Invoice", "Consignment withdrawal", "Payment", "Entry"


def _check_viewer() -> None:
	user = frappe.session.user
	if user != "Administrator" and not set(VIEWERS) & set(frappe.get_roles(user)):
		frappe.throw(_("Only supplier accounts open the supplier ledger."), frappe.PermissionError)


def _lines(supplier: str, company: str, to_date: str | None = None) -> list:
	filters = {"party_type": SUPPLIER, "party": supplier, "company": company, "is_cancelled": 0}
	if to_date:
		filters["posting_date"] = ("<=", to_date)
	return frappe.get_all(
		"GL Entry",
		filters,
		[
			"name", "posting_date", "voucher_type", "voucher_no", "against_voucher_type", "against_voucher",
			"debit", "credit", "project", "remarks",
		],
		order_by="posting_date asc, creation asc, name asc",
	)  # fmt: skip


def _invoice_shares(invoices: set[str]) -> dict[str, dict]:
	"""{invoice: {project: fraction}}, by the value of its lines."""
	values: dict[str, dict] = {}
	if not invoices:
		return values
	rows = frappe.get_all(
		"Purchase Invoice Item", {"parent": ("in", list(invoices))}, ["parent", "project", "base_net_amount"]
	)
	for row in rows:
		lines = values.setdefault(row.parent, {})
		lines[row.project] = lines.get(row.project, 0) + flt(row.base_net_amount)
	shares = {}
	for invoice, lines in values.items():
		total = sum(lines.values())
		if total:
			shares[invoice] = {project: value / total for project, value in lines.items()}
	return shares


def _invoice_of(line) -> str | None:
	if line.against_voucher_type == INVOICE and line.against_voucher:
		return line.against_voucher
	return line.voucher_no if line.voucher_type == INVOICE else None


def _split(lines: list) -> dict:
	"""{project: amount owed}; each line's rounding stays with its last station."""
	shares = _invoice_shares({_invoice_of(line) for line in lines} - {None})
	totals: dict = {}
	for line in lines:
		net = flt(line.credit) - flt(line.debit)
		parts = shares.get(_invoice_of(line)) or {line.project: 1}
		left = net
		projects = list(parts)
		for project in projects[:-1]:
			amount = flt(net * parts[project], MONEY_DIGITS)
			totals[project] = totals.get(project, 0) + amount
			left -= amount
		totals[projects[-1]] = totals.get(projects[-1], 0) + left
	return totals


def _station_rows(totals: dict) -> list[dict]:
	projects = [p for p in totals if p]
	stations = dict(
		frappe.get_all("Project", {"name": ("in", projects or [""])}, ["name", "sp_station"], as_list=True)
	)
	return [
		{
			"project": project,
			"station": stations.get(project) or project,
			"amount": flt(amount, MONEY_DIGITS),
		}
		for project, amount in sorted(totals.items(), key=lambda r: (r[0] is None, r[0] or ""))
		if flt(amount, MONEY_DIGITS)
	]


def _withdrawals(invoices: set[str]) -> set[str]:
	"""The invoices that bill a consignment withdrawal."""
	if not invoices:
		return set()
	rows = frappe.get_all(
		"Purchase Invoice Item",
		{"parent": ("in", list(invoices)), "purchase_order": ("is", "set")},
		["parent", "purchase_order"],
	)
	flagged = set(
		frappe.get_all(
			"Purchase Order",
			{"name": ("in", [r.purchase_order for r in rows] or [""]), "sp_is_consignment_conversion": 1},
			pluck="name",
		)
	)
	return {r.parent for r in rows if r.purchase_order in flagged}


def _kind(line, withdrawals: set[str]) -> str:
	if line.voucher_type == INVOICE:
		return WITHDRAWAL if line.voucher_no in withdrawals else INVOICE_KIND
	return PAYMENT if line.voucher_type == "Payment Entry" else OTHER


@frappe.whitelist()
def supplier_ledger(
	supplier: str, company: str | None = None, from_date: str | None = None, to_date: str | None = None
) -> dict:
	"""The ledger for the period, with the balance carried into it."""
	_check_viewer()
	company = company or default_company()
	lines = _lines(supplier, company, to_date)
	start = getdate(from_date) if from_date else None
	withdrawals = _withdrawals({l.voucher_no for l in lines if l.voucher_type == INVOICE})
	opening = balance = 0.0
	rows = []
	for line in lines:
		balance = flt(balance + flt(line.credit) - flt(line.debit), MONEY_DIGITS)
		if start and getdate(line.posting_date) < start:
			opening = balance
			continue
		rows.append(
			{
				"date": str(line.posting_date),
				"kind": _kind(line, withdrawals),
				"voucher_type": line.voucher_type,
				"voucher_no": line.voucher_no,
				"against": line.against_voucher if line.against_voucher != line.voucher_no else None,
				"project": line.project,
				"debit": flt(line.debit),
				"credit": flt(line.credit),
				"balance": balance,
				"remarks": line.remarks,
			}
		)
	week = add_days(getdate(nowdate()), WEEK)
	invoices = open_invoices(supplier, company)
	for invoice in invoices:
		invoice.overdue = bool(invoice.due_date and getdate(invoice.due_date) < getdate(nowdate()))
		invoice.due_this_week = bool(invoice.due_date and getdate(invoice.due_date) <= week)
	return {
		"supplier": supplier,
		"company": company,
		"currency": frappe.get_cached_value("Company", company, "default_currency"),
		"opening": opening,
		"balance": balance,
		"rows": rows,
		"stations": _station_rows(_split(lines)),
		"open_invoices": invoices,
		"due_this_week": sum(flt(i.outstanding_amount) for i in invoices if i.due_this_week),
	}


def dues_this_week(company: str | None = None) -> dict:
	"""What suppliers are owed within a week; the late part is inside the total."""
	week = add_days(getdate(nowdate()), WEEK)
	filters = {"docstatus": 1, "outstanding_amount": (">", 0), "due_date": ("<=", week)}
	if company:
		filters["company"] = company
	rows = frappe.get_all(INVOICE, filters, ["outstanding_amount", "due_date"])
	today = getdate(nowdate())
	return {
		"amount": sum(flt(r.outstanding_amount) for r in rows),
		"overdue": sum(flt(r.outstanding_amount) for r in rows if getdate(r.due_date) < today),
		"week_end": str(week),
	}
