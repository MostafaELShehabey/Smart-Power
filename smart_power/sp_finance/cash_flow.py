"""R2 Cash flow (SP-140): will the coming collections cover the supplier dues?

    opening     the balances of the official accounts today (+ the transit accounts, optional)
    inflows     the open stations' unpaid instalments (SP-81) and the open cheques (SP-118:
                Received, Due or Deposited), each by its due date
    outflows    the supplier invoices' outstanding amounts (SP-86), by due date

A cheque usually pays its own station's instalments, and it is not a payment until it is
collected, so counting both would count that money twice. Each open cheque counts on its own
due date, and the station's unpaid instalments count only the part its open cheques do not cover,
oldest first (owner's decision 22-11-2026).

Buckets: weeks (7 days from today: week 1 is today to 6 days on) or calendar months (month 1 is
today to the month's end), over a horizon of 4-26 weeks or 1-12 months. Each bucket's closing is
its opening + inflows - outflows, and the next bucket opens at it. What fell due before today
shows in its own "Overdue" row and is not counted in the running balance: it is not certain.
The known obligations (A12, SP-127) join the outflows when they are built.

    rows(filters)   the report rows, overdue first
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, get_first_day, get_last_day, getdate, today

from smart_power.sp_finance.accounts import OFFICIAL, TRANSIT
from smart_power.sp_finance.cheques import DEPOSITED, DUE, RECEIVED

WEEK, MONTH = "Week", "Month"
HORIZONS = {WEEK: (4, 26, 12), MONTH: (1, 12, 6)}  # sp-allow-number: the story's min, max; a default
DAYS_IN_WEEK = 7  # sp-allow-number: a week
OPEN_CHEQUES = (RECEIVED, DUE, DEPOSITED)
OVERDUE = "overdue"
MONEY = ("opening", "installments", "cheques", "inflow", "supplier_dues", "net", "closing")
MONEY_DIGITS = 2  # sp-allow-number: currency precision


def _filters(filters) -> frappe._dict:
	filters = frappe._dict(filters or {})
	filters.company = filters.get("company") or frappe.defaults.get_user_default("Company")
	if not filters.company:
		frappe.throw(_("Choose the company."))
	filters.granularity = filters.get("granularity") or WEEK
	if filters.granularity not in HORIZONS:
		frappe.throw(_("Show the cash flow by week or by month."))
	low, high, default = HORIZONS[filters.granularity]
	filters.horizon = min(max(cint(filters.get("horizon")) or default, low), high)
	filters.as_of = getdate(filters.get("as_of") or today())
	return filters


def buckets(start, granularity: str, horizon: int) -> list[tuple]:
	"""[(from, to)]: weeks from the given day, or the rest of its month then calendar months."""
	start = getdate(start)
	if granularity == WEEK:
		return [
			(add_days(start, DAYS_IN_WEEK * i), add_days(start, DAYS_IN_WEEK * (i + 1) - 1))
			for i in range(horizon)
		]
	out = [(start, get_last_day(start))]
	for i in range(1, horizon):
		first = get_first_day(add_months(start, i))
		out.append((first, get_last_day(first)))
	return out


def opening(company: str, as_of, include_transit: bool = False) -> float:
	kinds = (OFFICIAL, TRANSIT) if include_transit else (OFFICIAL,)
	(amount,) = frappe.db.sql(
		"""select coalesce(sum(gle.debit - gle.credit), 0)
		from `tabGL Entry` gle join `tabAccount` acc on acc.name = gle.account
		where gle.company = %(company)s and gle.is_cancelled = 0 and gle.posting_date <= %(as_of)s
			and acc.sp_account_kind in %(kinds)s""",
		{"company": company, "as_of": as_of, "kinds": kinds},
	)[0]
	return flt(amount)


def inflows(company: str, as_of) -> list[dict]:
	"""[{date, amount, kind, reference}]: the open cheques, and the instalments they do not cover."""
	from smart_power.sp_stations.installments import OPEN_STATUSES, allocation

	cheques = frappe.get_all(
		"SP Cheque",
		{"company": company, "status": ("in", OPEN_CHEQUES)},
		["name", "station", "amount", "due_date"],
	)
	covered: dict[str, float] = {}
	lines = []
	for c in cheques:
		covered[c.station] = covered.get(c.station, 0.0) + flt(c.amount)
		lines.append(
			{"date": getdate(c.due_date), "amount": flt(c.amount), "kind": "cheques", "reference": c.name}
		)
	for name in frappe.get_all(
		"SP Station",
		{"company": company, "status": ("in", OPEN_STATUSES), "sales_order": ("is", "set")},
		pluck="name",
	):
		doc = frappe.get_doc("SP Station", name)
		cover = covered.get(name, 0.0)
		for row in allocation(doc, on=as_of):  # oldest first
			left = flt(row["left"])
			take = min(left, cover)
			cover -= take
			left -= take
			if left > 0 and row.get("due_date"):
				lines.append(
					{
						"date": getdate(row["due_date"]),
						"amount": left,
						"kind": "installments",
						"reference": name,
					}
				)
	return lines


def outflows(company: str) -> list[dict]:
	rows = frappe.get_all(
		"Purchase Invoice",
		{"company": company, "docstatus": 1, "outstanding_amount": (">", 0)},
		["name", "outstanding_amount", "due_date", "posting_date"],
	)
	return [
		{
			"date": getdate(r.due_date or r.posting_date),
			"amount": flt(r.outstanding_amount),
			"kind": "supplier_dues",
			"reference": r.name,
		}
		for r in rows
	]


def _row(label: str, start=None, end=None) -> dict:
	return {"period": label, "from_date": start, "to_date": end, "is_overdue": 0} | dict.fromkeys(MONEY, 0.0)


def rows(filters=None) -> list[dict]:
	filters = _filters(filters)
	periods = buckets(filters.as_of, filters.granularity, filters.horizon)
	label = _("Week {0}") if filters.granularity == WEEK else _("Month {0}")
	out = [_row(label.format(i + 1), start, end) for i, (start, end) in enumerate(periods)]
	late = _row(_("Overdue"), None, add_days(filters.as_of, -1))
	late["is_overdue"] = 1
	for line in [*inflows(filters.company, filters.as_of), *outflows(filters.company)]:
		if line["date"] < filters.as_of:
			target = late
		else:
			target = next((r for r in out if r["from_date"] <= line["date"] <= r["to_date"]), None)
		if target is not None:
			target[line["kind"]] += line["amount"]
	balance = opening(filters.company, filters.as_of, cint(filters.get("include_transit")))
	for row in [late, *out]:
		row["inflow"] = row["installments"] + row["cheques"]
		row["net"] = row["inflow"] - row["supplier_dues"]
	for row in out:
		row["opening"] = balance
		balance = row["closing"] = balance + row["net"]
	for row in [late, *out]:
		for field in MONEY:
			row[field] = flt(row[field], MONEY_DIGITS)
	late["opening"] = late["closing"] = None  # not certain: kept out of the running balance
	return [late, *out]


def chart(data: list[dict]) -> dict:
	periods = [r for r in data if not r["is_overdue"]]
	return {
		"data": {
			"labels": [r["period"] for r in periods],
			"datasets": [{"name": _("Closing balance"), "values": [r["closing"] for r in periods]}],
		},
		"type": "line",
	}
