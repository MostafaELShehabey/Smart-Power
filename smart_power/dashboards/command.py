"""AD1 Command dashboard (SP-138): the owner runs the company from one screen.

Four rows of numbers for a month, and the list of what waits for the admin. Every number is a
card that says where a click goes: the list or report behind it, with the same filter.

    money        contracted (stations whose contract is dated in the month), collected (confirmed
                 customer payments dated in the month), outstanding on customers, overdue,
                 supplier payable, the official accounts' balances and the cash people hold, with
                 days held (A3 Treasury). Balances are today's, whatever month is picked.
    sales        R6 Conversion for the month (SP-144): requests by channel, quotes sent, won and
                 win rate, lost as "price check only"; requests past the quote clock now (Q3's
                 Overdue view); discounts given and quotes out of the margin range in the month
    operations   stations by status, late deliveries (a submitted PO past its schedule date and
                 not fully received), stations technically closed but not paid
    centers      R4 Center P&L for the month (SP-142): projects, showroom, winch, Jumbo car and
                 the company total (internal charges eliminated); and each station technically
                 closed in the month, its accepted quote's profit (the estimate) beside its
                 profit so far (the actual)
    attention    payments and deposits to confirm (A1), the open review items the owner acts on
                 (write-offs, count differences, abnormal flags, overrides, edits with a reason;
                 RV2) and the inactive cases (SP-71)

    get(month)   the dashboard for "YYYY-MM" (default: this month), admin only

Cached five minutes per company and month. The key carries the last change of the confirmed
money and the review items, so a confirmation shows at once.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_first_day, get_last_day, getdate, now_datetime, nowdate

ADMIN_ROLES = ("SP Admin", "System Manager")
CACHE_SECONDS = 300  # sp-allow-number: the story's five-minute cache
CACHE_KEY = "sp_command_dashboard"
INT, CURRENCY, PERCENT_TYPE = "Int", "Currency", "Percent"
RED, ORANGE, GREEN, GRAY, BLUE = "red", "orange", "green", "gray", "blue"
STATION, CASE, PAYMENT = "SP Station", "SP Case", "SP Customer Payment"
CANCELLED, TECH_CLOSED, FIN_CLOSED = "Cancelled", "Technically closed", "Financially closed"
STATION_STATUSES = ("Open", "Purchasing", "Installing", TECH_CLOSED, FIN_CLOSED)
CLOSED_CASE_STATUSES = ("Won", "Lost")
PO_DONE_STATUSES = ("Closed", "Completed", "On Hold")
FULLY_RECEIVED = 100  # sp-allow-number: per_received of a fully received PO, a percentage
PRICE_CHECK_ONLY = "PRICE_CHECK_ONLY"
# the review centre's tabs on the attention list, in the story's order
ATTENTION_TABS = ("Write-off", "Count Difference", "Abnormal", "Override", "Edit")
# the confirmed money and the review items: a change to any of them refreshes the cache
WATCHED = (PAYMENT, "SP Transfer", "SP Review Item", "SP Cash Box Day", "SP Custody Settlement")


def _check_admin() -> None:
	if frappe.session.user != "Administrator" and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("The command dashboard is the admin's."), frappe.PermissionError)


def _company() -> str:
	from smart_power.sp_core.services.company import COMPANY_SETTINGS

	company = (
		frappe.db.get_single_value(COMPANY_SETTINGS, "company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
		or frappe.defaults.get_user_default("Company")
	)
	if not company:
		frappe.throw(_("Set the company in Company Settings first."))
	return company


def _period(month: str | None) -> tuple:
	start = getdate(f"{month}-01") if month else get_first_day(nowdate())
	return get_first_day(start), get_last_day(start)


def _version() -> str:
	"""The last change of the watched records, so the cache key moves when one changes."""
	parts = []
	for doctype in WATCHED:
		if frappe.db.table_exists(doctype):
			last = frappe.get_all(doctype, fields=[{"MAX": "modified"}], as_list=True)
			parts.append(str(last[0][0] if last else ""))
	return "|".join(parts)


def card(key, label, value, *, fieldtype=INT, indicator=GRAY, note="", route=None, options=None) -> dict:
	return {
		"key": key,
		"label": label,
		"value": value,
		"fieldtype": fieldtype,
		"indicator": indicator,
		"note": note,
		"route": route or [],
		"route_options": options or {},
	}


def _between(from_date, to_date) -> list:
	return ["between", [str(from_date), str(to_date)]]


@frappe.whitelist()
def get(month: str | None = None) -> dict:
	"""The dashboard for a month ("YYYY-MM"), cached five minutes."""
	_check_admin()
	from_date, to_date = _period(month)
	company = _company()
	key = f"{CACHE_KEY}:{company}:{from_date}:{_version()}"
	cached = frappe.cache.get_value(key)
	if cached:
		return cached
	data = build(company, from_date, to_date)
	frappe.cache.set_value(key, data, expires_in_sec=CACHE_SECONDS)
	return data


def build(company: str, from_date, to_date) -> dict:
	money, official, transit = _money(company, from_date, to_date)
	sales, channels = _sales(from_date, to_date)
	operations, statuses = _operations(company)
	centers, projects = _centers(company, from_date, to_date)
	return {
		"company": company,
		"month": str(from_date)[:7],
		"from_date": str(from_date),
		"to_date": str(to_date),
		"sections": [
			{"key": "money", "label": _("Money"), "cards": money},
			{"key": "sales", "label": _("Sales"), "cards": sales},
			{"key": "operations", "label": _("Operations"), "cards": operations},
		],
		"official": official,
		"transit": transit,
		"channels": channels,
		"statuses": statuses,
		"centers": centers,
		"projects": projects,
		"attention": _attention(),
	}


# --- money -----------------------------------------------------------------------------------------


def _money(company, from_date, to_date) -> tuple[list, list, list]:
	from smart_power.sp_finance.treasury import treasury

	period = _between(from_date, to_date)
	not_cancelled = ["!=", CANCELLED]
	contracted = frappe.get_all(
		STATION,
		{"company": company, "status": not_cancelled, "contract_date": period},
		[{"SUM": "agreed_amount"}, {"COUNT": "name"}],
		as_list=True,
	)[0]
	collected = frappe.get_all(
		PAYMENT,
		{"company": company, "status": "Confirmed", "work_date": period},
		[{"SUM": "amount"}, {"COUNT": "name"}],
		as_list=True,
	)[0]
	stations = frappe.get_all(
		STATION,
		{"company": company, "status": not_cancelled},
		["remaining_amount", "overdue_amount"],
	)
	outstanding = sum(flt(s.remaining_amount) for s in stations if flt(s.remaining_amount) > 0)
	overdue = sum(flt(s.overdue_amount) for s in stations)
	payable = frappe.get_all(
		"Purchase Invoice",
		{"company": company, "docstatus": 1, "outstanding_amount": [">", 0]},
		[{"SUM": "outstanding_amount"}],
		as_list=True,
	)[0][0]
	money = treasury(company)
	official = [{"account_name": r["account_name"], "balance": r["balance"]} for r in money["official"]]
	transit = [
		{
			"account_name": r["account_name"],
			"holder_name": r["holder_name"],
			"balance": r["balance"],
			"days_held": r["days_held"],
			"limit": r["limit"],
			"over": r["over"],
		}
		for r in money["transit"]
		if flt(r["balance"])
	]
	treasury_route = ["sp-treasury"]
	cards = [
		card(
			"contracted",
			_("Contracted this month"),
			flt(contracted[0]),
			fieldtype=CURRENCY,
			note=_("{0} stations").format(cint(contracted[1])),
			route=["List", STATION],
			options={"contract_date": period, "status": not_cancelled},
		),
		card(
			"collected",
			_("Collected this month"),
			flt(collected[0]),
			fieldtype=CURRENCY,
			indicator=GREEN,
			note=_("{0} payments").format(cint(collected[1])),
			route=["List", PAYMENT],
			options={"status": "Confirmed", "work_date": period},
		),
		card(
			"outstanding",
			_("Outstanding on customers"),
			outstanding,
			fieldtype=CURRENCY,
			route=["query-report", "SP Customer Balances"],
		),
		card(
			"overdue",
			_("Overdue"),
			overdue,
			fieldtype=CURRENCY,
			indicator=RED if overdue else GREEN,
			route=["List", STATION],
			options={"has_overdue": 1, "status": not_cancelled},
		),
		card(
			"supplier_payable",
			_("Supplier payable"),
			flt(payable),
			fieldtype=CURRENCY,
			route=["List", "Purchase Invoice"],
			options={"docstatus": 1, "outstanding_amount": [">", 0]},
		),
		card(
			"official",
			_("Official accounts"),
			flt(money["totals"]["official"]),
			fieldtype=CURRENCY,
			indicator=BLUE,
			route=treasury_route,
		),
		card(
			"transit",
			_("Cash with people"),
			flt(money["totals"]["transit"]),
			fieldtype=CURRENCY,
			indicator=RED if any(r["over"] for r in transit) else GRAY,
			note=_("{0} over the days limit").format(sum(1 for r in transit if r["over"])),
			route=treasury_route,
		),
	]
	return cards, official, transit


# --- sales -----------------------------------------------------------------------------------------


def overdue_requests() -> int:
	"""Open requests past the quote clock now: what Q3's Overdue view lists."""
	from smart_power.sp_sales.quote_clock import OVERDUE, clock
	from smart_power.sp_sales.quote_queue import OPEN_STATUSES

	rows = frappe.get_all(
		CASE,
		{"status": ("in", OPEN_STATUSES), "quote_sent_at": ("is", "not set")},
		["creation", "quote_sent_at"],
	)
	return sum(1 for r in rows if clock(r)["state"] == OVERDUE)


def _sales(from_date, to_date) -> tuple[list, list]:
	from smart_power.sp_core.services.lists import by_code
	from smart_power.sp_sales import conversion as cv

	filters = {"from_date": str(from_date), "to_date": str(to_date)}
	rows = cv.rows({**filters, "group_by": cv.CHANNEL})
	total = next(r for r in rows if r.get("is_total"))
	channels = [{"channel": r["key"], "label": r["group"], "requests": r["requests"]} for r in rows[:-1]]
	reasons = cv.rows({**filters, "group_by": cv.REASON})
	price_check = by_code("Lost Reason", PRICE_CHECK_ONLY)
	price_lost = next((r["lost"] for r in reasons if price_check and r["key"] == price_check), 0)
	discounts = frappe.db.sql(
		"""select count(d.name), coalesce(sum(d.amount), 0)
		from `tabSP Quote Discount` d join `tabQuotation` q on q.name = d.parent
		where d.parenttype = 'Quotation' and q.docstatus < 2 and d.kind = 'Discount'
			and d.given_on between %s and %s""",
		(f"{from_date} 00:00:00", f"{to_date} 23:59:59"),
	)[0]
	out_of_margin = frappe.db.count(
		"SP Review Item",
		{"category": "Margin", "creation": _between(f"{from_date} 00:00:00", f"{to_date} 23:59:59")},
	)
	late = overdue_requests()
	report = ["query-report", "SP Conversion"]
	review = ["sp-review-centre"]
	cards = [
		card(
			"requests",
			_("Requests this month"),
			total["requests"],
			route=report,
			options={**filters, "group_by": cv.CHANNEL},
		),
		card(
			"over_24h",
			_("Requests over 24 h"),
			late,
			indicator=RED if late else GREEN,
			note=_("Open now"),
			route=["sp-quote-queue"],
			options={"view": "Overdue"},
		),
		card("quoted", _("Quotes sent"), total["quoted"], route=report, options=filters),
		card(
			"won",
			_("Won"),
			total["won"],
			indicator=GREEN,
			note=_("Win rate {0}%").format(total["win_rate"]),
			route=report,
			options=filters,
		),
		card(
			"win_rate",
			_("Win rate"),
			total["win_rate"],
			fieldtype=PERCENT_TYPE,
			route=report,
			options=filters,
		),
		card(
			"price_check",
			_("Lost as price check only"),
			price_lost,
			route=report,
			options={**filters, "group_by": cv.REASON},
		),
		card(
			"discounts",
			_("Discounts given"),
			flt(discounts[1]),
			fieldtype=CURRENCY,
			note=_("{0} discounts").format(cint(discounts[0])),
			route=review,
			options={"category": "Discount"},
		),
		card(
			"out_of_margin",
			_("Quotes out of margin range"),
			out_of_margin,
			indicator=ORANGE if out_of_margin else GREEN,
			route=review,
			options={"category": "Margin"},
		),
	]
	return cards, channels


# --- operations ------------------------------------------------------------------------------------


def _operations(company) -> tuple[list, list]:
	counts = dict(
		frappe.get_all(
			STATION,
			{"company": company, "status": ("!=", CANCELLED)},
			["status", {"COUNT": "name"}],
			group_by="status",
			as_list=True,
		)
	)
	statuses = [{"status": s, "label": _(s), "count": cint(counts.get(s))} for s in STATION_STATUSES]
	late_filters = {
		"company": company,
		"docstatus": 1,
		"status": ["not in", list(PO_DONE_STATUSES)],
		"per_received": ["<", FULLY_RECEIVED],
		"schedule_date": ["<", nowdate()],
	}
	late = frappe.db.count("Purchase Order", late_filters)
	unpaid_filters = {"company": company, "status": TECH_CLOSED, "remaining_amount": [">", 0]}
	unpaid = frappe.get_all(
		STATION, unpaid_filters, [{"SUM": "remaining_amount"}, {"COUNT": "name"}], as_list=True
	)[0]
	open_count = sum(c["count"] for c in statuses if c["status"] not in (TECH_CLOSED, FIN_CLOSED))
	cards = [
		card(
			"stations_open",
			_("Stations in progress"),
			open_count,
			indicator=BLUE,
			route=["List", STATION],
			options={"status": ["in", list(STATION_STATUSES[:3])]},
		),
		card(
			"late_deliveries",
			_("Late deliveries"),
			late,
			indicator=RED if late else GREEN,
			note=_("Purchase orders past their date"),
			route=["List", "Purchase Order"],
			options={k: v for k, v in late_filters.items() if k != "company"},
		),
		card(
			"closed_unpaid",
			_("Closed but not paid"),
			cint(unpaid[1]),
			indicator=ORANGE if cint(unpaid[1]) else GREEN,
			note=frappe.format(flt(unpaid[0]), "Currency"),
			route=["List", STATION],
			options={k: v for k, v in unpaid_filters.items() if k != "company"},
		),
	]
	return cards, statuses


# --- centers ---------------------------------------------------------------------------------------


def _centers(company, from_date, to_date) -> tuple[list, list]:
	from smart_power.sp_finance import center_pnl
	from smart_power.sp_finance.centers import JUMBO, PROJECTS, SHOWROOM, WINCH

	filters = {"company": company, "from_date": str(from_date), "to_date": str(to_date)}
	rows = center_pnl.summary(filters)
	shown = (PROJECTS, SHOWROOM, WINCH, JUMBO, center_pnl.TOTAL)
	centers = [
		{
			"key": r["center_key"],
			"label": r["center"],
			"revenue": r["revenue"],
			"cost": flt(r["cost"] + r["indirect"]),
			"profit": r["profit"],
			"route": ["query-report", "SP Center PnL"],
			"route_options": filters,
		}
		for r in rows
		if not r.get("station") and not r.get("no_station") and r["center_key"] in shown
	]
	return centers, _projects(company, from_date, to_date)


def _projects(company, from_date, to_date) -> list[dict]:
	"""Each station technically closed in the month: its accepted quote's profit, and its profit
	so far on the Center P&L (every line from its contract to the month's end)."""
	from smart_power.sp_finance import center_pnl

	closed = frappe.get_all(
		STATION,
		{"company": company, "tech_closed_on": _between(from_date, to_date), "status": ("!=", CANCELLED)},
		["name", "customer_name", "quotation_accepted", "contract_date", "creation"],
		order_by="tech_closed_on asc",
	)
	if not closed:
		return []
	start = min(getdate(s.contract_date or s.creation) for s in closed)
	actual = {
		r["station"]: r["profit"]
		for r in center_pnl.summary({"company": company, "from_date": str(start), "to_date": str(to_date)})
		if r.get("station")
	}
	quotes = {s.quotation_accepted for s in closed if s.quotation_accepted}
	estimate = dict(
		frappe.get_all(
			"Quotation", {"name": ("in", list(quotes) or [""])}, ["name", "sp_profit"], as_list=True
		)
	)
	return [
		{
			"station": s.name,
			"customer_name": s.customer_name,
			"estimate": flt(estimate.get(s.quotation_accepted)),
			"actual": flt(actual.get(s.name)),
			"difference": flt(actual.get(s.name)) - flt(estimate.get(s.quotation_accepted)),
		}
		for s in closed
	]


# --- attention -------------------------------------------------------------------------------------


def _attention() -> list[dict]:
	from smart_power.sp_core.review_centre import _labels
	from smart_power.sp_core.services.settings import get_value
	from smart_power.sp_finance.confirmations import pending

	waiting = pending()
	labels = _labels()
	open_counts = dict(
		frappe.get_all(
			"SP Review Item",
			{"status": "Open", "category": ("in", ATTENTION_TABS)},
			["category", {"COUNT": "name"}],
			group_by="category",
			as_list=True,
		)
	)
	items = [
		card(
			"confirm",
			_("Payments and deposits to confirm"),
			waiting["count"],
			indicator=ORANGE if waiting["count"] else GREEN,
			note=frappe.format(flt(waiting["amount"]), "Currency"),
			route=["sp-confirmations"],
		)
	]
	for category in ATTENTION_TABS:
		count = cint(open_counts.get(category))
		items.append(
			card(
				f"review_{frappe.scrub(category)}",
				labels[category],
				count,
				indicator=ORANGE if count else GREEN,
				route=["sp-review-centre"],
				options={"category": category},
			)
		)
	days = cint(get_value("case_inactivity_days"))
	if days:
		cutoff = add_days(now_datetime(), -days)
		inactive_filters = {
			"status": ["not in", list(CLOSED_CASE_STATUSES)],
			"last_action_at": ["<", str(cutoff)],
		}
		inactive = frappe.db.count(CASE, inactive_filters)
		items.append(
			card(
				"inactive_cases",
				_("Inactive cases"),
				inactive,
				indicator=ORANGE if inactive else GREEN,
				note=_("No action for {0} days").format(days),
				route=["List", CASE],
				options=inactive_filters,
			)
		)
	return items
