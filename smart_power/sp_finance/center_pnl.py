"""R4 Center P&L (SP-142): does each station, the showroom, the winch and the Jumbo car make money?

Every submitted GL line on an income or expense account in the period counts for the financial
center it was posted on (SP-27). A line on a child the admin added under a center counts for
that center; any other cost center shows as "Other". Projects open per station, through the
line's project (a station is its Project, never a cost center).

    revenue          income lines (credit - debit)
    direct cost      expense lines (debit - credit), except the indirect split
    indirect share   the "Indirect Split" lines (SP-124): a station's or a center's share of the
                     pool, and on the Indirect Pool itself the pool going out, so it nets to 0
    internal in/out  the income and expense lines of internal charges (sp_internal_charge: a
                     station's winch job, SP-108). They count in each center, and the
                     elimination row takes them out of the company total: equal and opposite,
                     so the company profit does not move. Showroom goods reach a station as a
                     stock transfer at cost (SP-88), which books no showroom income.

    summary(filters)  the report rows: centers, stations under Projects, elimination, total
    lines(filters)    the GL lines behind one cell (the drill-down)
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, get_last_day, getdate, nowdate

from smart_power.sp_core.services.settings import get_value
from smart_power.sp_finance.centers import INDIRECT, JUMBO, PROJECTS, SHOWROOM, WINCH
from smart_power.sp_finance.indirect_split import EVENT as SPLIT_EVENT

OTHER, ELIMINATION, TOTAL = "other", "elimination", "total"
CENTERS = (PROJECTS, SHOWROOM, WINCH, JUMBO, INDIRECT)
LABELS = {
	PROJECTS: "Projects",
	SHOWROOM: "Showroom",
	WINCH: "Winch",
	JUMBO: "Jumbo Car",
	INDIRECT: "Indirect Pool",
	OTHER: "Other",
	ELIMINATION: "Internal charges eliminated",
	TOTAL: "Company total",
}
REVENUE, COST, SHARE = "revenue", "cost", "indirect"
KINDS = {"Revenue": REVENUE, "Direct Cost": COST, "Indirect Share": SHARE}
MONEY = ("revenue", "cost", "indirect", "profit", "internal_in", "internal_out")
PERCENT = 100  # sp-allow-number: margin as a percentage
MONEY_DIGITS = 2  # sp-allow-number: currency precision


def _filters(filters) -> frappe._dict:
	filters = frappe._dict(filters or {})
	filters.company = filters.get("company") or frappe.defaults.get_user_default("Company")
	if not filters.company:
		frappe.throw(_("Choose the company."))
	filters.from_date = getdate(filters.get("from_date") or get_first_day(nowdate()))
	filters.to_date = getdate(filters.get("to_date") or get_last_day(nowdate()))
	if filters.from_date > filters.to_date:
		frappe.throw(_("The from date is after the to date."))
	return filters


def _resolver(company: str):
	"""cost center -> its center key: the center set in Smart Power Settings, or a child under it."""
	tree = {
		r.name: (r.lft, r.rgt)
		for r in frappe.get_all("Cost Center", {"company": company}, ["name", "lft", "rgt"])
	}
	ranges = [(key, tree[name]) for key in CENTERS if (name := get_value(f"center_{key}")) in tree]
	cache = {}

	def key_of(cost_center: str | None) -> str:
		if cost_center not in cache:
			lft, rgt = tree.get(cost_center, (None, None))
			cache[cost_center] = next(
				(key for key, (lo, hi) in ranges if lft is not None and lo <= lft and rgt <= hi), OTHER
			)
		return cache[cost_center]

	return key_of


def _gl(filters, grouped: bool = True) -> list[dict]:
	"""Income and expense GL lines of the period, with their station and posting event."""
	fields = (
		"gle.cost_center, pr.sp_station as station, acc.root_type, je.sp_posting_event as event,"
		" coalesce(je.sp_internal_charge, 0) as internal, sum(gle.credit - gle.debit) as net"
	)
	group = "group by gle.cost_center, pr.sp_station, acc.root_type, je.sp_posting_event, internal"
	if not grouped:
		fields = (
			"gle.name, gle.posting_date, gle.voucher_type, gle.voucher_no, gle.account, gle.cost_center,"
			" pr.sp_station as station, acc.root_type, je.sp_posting_event as event,"
			" coalesce(je.sp_internal_charge, 0) as internal, gle.credit - gle.debit as net, gle.remarks"
		)
		group = "order by gle.posting_date, gle.creation"
	return frappe.db.sql(  # nosemgrep
		f"""select {fields}
		from `tabGL Entry` gle
		join `tabAccount` acc on acc.name = gle.account
		left join `tabProject` pr on pr.name = gle.project
		left join `tabJournal Entry` je
			on gle.voucher_type = 'Journal Entry' and je.name = gle.voucher_no
		where gle.company = %(company)s and gle.is_cancelled = 0
			and acc.root_type in ('Income', 'Expense')
			and gle.posting_date between %(from_date)s and %(to_date)s
		{group}""",
		filters,
		as_dict=True,
	)


def _kind(line) -> str:
	if line.root_type == "Income":
		return REVENUE
	return SHARE if line.event == SPLIT_EVENT else COST


def _empty(key: str, station: str | None = None, indent: int = 0) -> dict:
	label = station or _(LABELS[key])
	return {"center": label, "center_key": key, "station": station, "indent": indent} | dict.fromkeys(
		MONEY, 0.0
	)


def _add(row: dict, line) -> None:
	kind = _kind(line)
	amount = flt(line.net) if kind == REVENUE else -flt(line.net)
	row[kind] += amount
	if cint(line.internal):
		row["internal_in" if kind == REVENUE else "internal_out"] += amount


def _finish(row: dict) -> dict:
	for field in MONEY:
		row[field] = flt(row[field], MONEY_DIGITS)
	row["profit"] = flt(row["revenue"] - row["cost"] - row["indirect"], MONEY_DIGITS)
	row["margin"] = flt(row["profit"] * PERCENT / row["revenue"], MONEY_DIGITS) if row["revenue"] else 0.0
	return row


def summary(filters=None) -> list[dict]:
	filters = _filters(filters)
	key_of = _resolver(filters.company)
	centers = {key: _empty(key) for key in (*CENTERS, OTHER)}
	stations: dict[str, dict] = {}
	for line in _gl(filters):
		key = key_of(line.cost_center)
		_add(centers[key], line)
		if key == PROJECTS:
			station = line.station or ""
			if station not in stations:
				stations[station] = _empty(PROJECTS, station or _("No station"), indent=1)
				stations[station]["station"] = station or None
				stations[station]["no_station"] = 0 if station else 1
			_add(stations[station], line)
	rows = [_finish(centers[PROJECTS])]
	rows += [_finish(stations[s]) for s in sorted(stations, key=lambda s: (not s, s))]
	rows += [_finish(centers[key]) for key in (*CENTERS[1:], OTHER) if key != OTHER or _moved(centers[key])]
	totals = _empty(TOTAL)
	for key in (*CENTERS, OTHER):
		for field in MONEY:
			totals[field] += centers[key][field]
	elimination = _empty(ELIMINATION)
	elimination["revenue"] = -totals["internal_in"]
	elimination["cost"] = -totals["internal_out"]
	for field in ("revenue", "cost"):
		totals[field] += elimination[field]
	totals["internal_in"] = totals["internal_out"] = 0.0
	return [*rows, _finish(elimination), _finish(totals)]


def _moved(row: dict) -> bool:
	return any(flt(row[field]) for field in ("revenue", "cost", "indirect"))


def lines(filters=None) -> list[dict]:
	"""The GL lines behind one cell: a center (and a station under Projects), and a column."""
	filters = _filters(filters)
	key_of = _resolver(filters.company)
	wanted = KINDS.get(filters.get("kind")) or filters.get("kind")
	out = []
	for line in _gl(filters, grouped=False):
		if filters.get("center") and key_of(line.cost_center) != filters.center:
			continue
		if filters.get("station") and line.station != filters.station:
			continue
		if cint(filters.get("no_station")) and line.station:
			continue
		kind = _kind(line)
		if wanted and kind != wanted:
			continue
		if cint(filters.get("internal_only")) and not cint(line.internal):
			continue
		line["kind"] = _(next(label for label, k in KINDS.items() if k == kind))
		line["amount"] = flt(line.net if kind == REVENUE else -flt(line.net), MONEY_DIGITS)
		line["center"] = _(LABELS[key_of(line.cost_center)])
		out.append(line)
	return out
