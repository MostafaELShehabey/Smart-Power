"""Customer balances (AR1, SP-120): per customer and station, and the customer's statement.

- Per station: agreed, paid (confirmed only), remaining, overdue, advances (Agri Bank), next due:
  the station's money (SP-73) plus overdue, from the contract's payment schedule (the instalments
  whose date has passed, less what was paid and written off), and advances, the station's
  balance on the Customer Advances account (SP-121 records them).
- The statement is the station's money in date order: the contract (debit), each confirmed payment
  and write-off (credit), with the running balance; it ends at the station's Remaining. (The
  agreed amount reaches the ledger only with the final invoice, SP-80, so a ledger-only statement
  would not show what is owed.)
- A collection officer sees only the stations they collect (SP Station permission hooks); the
  admin, the accountant and the station roles see all.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from smart_power.sp_stations.money import _agreed_and_schedule

STATION = "SP Station"
ADVANCES_ACCOUNT = "Customer Advances - Agri Bank"
COLLECTOR = "SP Collection Officer"
# the roles that read every station (SP Station's own permissions)
ALL_STATIONS = (
	"System Manager",
	"SP Admin",
	"SP Project Manager",
	"SP Installation Manager",
	"SP Customer Followup",
	"SP Followup All",
	"SP Accountant",
)


def own_stations_only(user: str | None = None) -> bool:
	"""A collection officer with no other station role sees only the stations they collect."""
	user = user or frappe.session.user
	if user == "Administrator":
		return False
	roles = set(frappe.get_roles(user))
	return COLLECTOR in roles and not roles & set(ALL_STATIONS)


def station_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	"""SP Station permission_query_conditions."""
	user = user or frappe.session.user
	if not own_stations_only(user):
		return ""
	return f"`tabSP Station`.`collection_owner` = {frappe.db.escape(user)}"


def station_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""SP Station has_permission: the same rule for one station."""
	user = user or frappe.session.user
	return not own_stations_only(user) or doc.collection_owner == user


def overdue(doc) -> float:
	"""What the instalments already due still lack (paid and written-off money covers the oldest)."""
	_agreed, schedule = _agreed_and_schedule(doc)
	due = sum(amount for date, amount in schedule if date < getdate(today()))
	covered = flt(doc.paid_amount) + flt(doc.write_off_amount)
	return max(due - covered, 0.0)


def advances(doc) -> float:
	"""The station's balance on the Customer Advances (Agri Bank) account."""
	if not doc.project:
		return 0.0
	account = frappe.db.get_value(
		"Account", {"company": doc.company, "account_name": ADVANCES_ACCOUNT, "is_group": 0}
	)
	if not account:
		return 0.0
	rows = frappe.get_all(
		"GL Entry",
		{"account": account, "project": doc.project, "is_cancelled": 0},
		["debit", "credit"],
	)
	# an asset: what was advanced on the customer's behalf (awaiting the bank) is its debit balance
	return sum(flt(r.debit) - flt(r.credit) for r in rows)


def station_rows(filters: dict | None = None) -> list[dict]:
	"""One row per station the user may see, with its balance."""
	filters = filters or {}
	where = {"status": ("!=", "Cancelled")}
	for key in ("customer", "collection_owner", "status"):
		if filters.get(key):
			where[key] = filters[key]
	rows = []
	for name in frappe.get_list(STATION, where, pluck="name", order_by="customer_name asc, name asc"):
		doc = frappe.get_doc(STATION, name)
		rows.append(
			{
				"customer": doc.customer,
				"customer_name": doc.customer_name,
				"station": doc.name,
				"status": doc.status,
				"agreed": flt(doc.agreed_amount),
				"paid": flt(doc.paid_amount),
				"pending": flt(doc.pending_amount),
				"remaining": flt(doc.remaining_amount),
				"overdue": overdue(doc),
				"advances": advances(doc),
				"next_due_date": doc.next_due_date,
				"next_due_amount": flt(doc.next_due_amount),
				"collection_owner": doc.collection_owner,
			}
		)
	return rows


# --- the statement ---------------------------------------------------------------------------------


def statement_lines(station: str) -> list[dict]:
	"""The station's money in date order with its running balance (ends at Remaining)."""
	doc = frappe.get_doc(STATION, station)
	events = []
	if flt(doc.agreed_amount):
		so_date = (
			frappe.db.get_value("Sales Order", doc.sales_order, "transaction_date")
			if doc.sales_order
			else None
		)
		events.append(
			{
				"date": getdate(doc.contract_date or so_date or doc.creation),
				"description": _("Contract {0}").format(
					doc.sales_order or doc.quotation_accepted or doc.name
				),
				"debit": flt(doc.agreed_amount),
				"credit": 0.0,
			}
		)
	if doc.project:
		for pe in frappe.get_all(
			"Payment Entry",
			{"project": doc.project, "docstatus": 1, "payment_type": "Receive", "party_type": "Customer"},
			["name", "posting_date", "paid_amount", "mode_of_payment", "reference_no"],
			order_by="posting_date asc, creation asc",
		):
			events.append(
				{
					"date": getdate(pe.posting_date),
					"description": _("Payment {0}").format(
						" · ".join(str(x) for x in (pe.mode_of_payment, pe.reference_no) if x) or pe.name
					),
					"debit": 0.0,
					"credit": flt(pe.paid_amount),
				}
			)
	for je in frappe.get_all(
		"Journal Entry",
		{
			"sp_source_doctype": STATION,
			"sp_source_name": doc.name,
			"sp_posting_event": "Write-off",
			"docstatus": 1,
		},
		["name", "posting_date", "total_debit"],
		order_by="posting_date asc",
	):
		events.append(
			{
				"date": getdate(je.posting_date),
				"description": _("Write-off {0}").format(je.name),
				"debit": 0.0,
				"credit": flt(je.total_debit),
			}
		)
	events.sort(key=lambda e: (e["date"], -e["debit"]))  # the contract first on its day
	balance = 0.0
	for e in events:
		balance += e["debit"] - e["credit"]
		e["balance"] = balance
	return events


def customer_statement(doc) -> frappe._dict:
	"""What the "SP Customer Statement" print shows for a station."""
	from smart_power.sp_core.printing import ar_date

	frappe.has_permission(STATION, "read", doc=doc, throw=True)
	lines = statement_lines(doc.name)
	for line in lines:
		line["date_ar"] = ar_date(line["date"])
	return frappe._dict(
		customer=doc.customer_name or doc.customer,
		station=doc.name,
		date=ar_date(today()),
		lines=lines,
		agreed=flt(doc.agreed_amount),
		paid=flt(doc.paid_amount),
		remaining=flt(doc.remaining_amount),
		overdue=overdue(doc),
		balance=lines[-1]["balance"] if lines else 0.0,
	)
