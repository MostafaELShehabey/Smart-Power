"""Home page cards (SP-38, G2): each person's numbers, by the work their roles do.

A card is a function registered with @card(key, label, variants). It returns the number, how to
show it (Int or Currency, an indicator colour, a short note) and where a click goes: a list with
the same filter, or a page. A user sees the cards of every variant their roles belong to
(VARIANTS); the cards are cached for a minute per user. Each card reads its own DocType, so a card
for something not built yet simply joins when its story lands.

    get_home()   the signed-in user's cards
"""

from collections.abc import Callable
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_datetime, getdate, now_datetime, nowdate

CACHE_SECONDS = 60  # sp-allow-number: the story's one-minute cache per user
SECONDS_PER_HOUR = 3600  # sp-allow-number: seconds in an hour
INT, CURRENCY = "Int", "Currency"
RED, ORANGE, GREEN, GRAY = "red", "orange", "green", "gray"
ADMIN = ("SP Admin", "System Manager")

# home variant → the roles whose holders get its cards
VARIANTS = {
	"intake": ("SP Lead Intake", "SP Customer Followup", "SP Followup All"),
	"marketing": ("SP Marketing Agent",),
	"tech_office": ("SP Quote Creator", "SP System Designer"),
	"projects": ("SP Project Manager", "SP Contract Manager"),
	"installations": ("SP Installation Manager", "SP Installation Technician", "SP Site Survey"),
	"store": ("SP Main Store Keeper", "SP Showroom Store Keeper", "SP Site Receiver"),
	"showroom": ("SP Showroom Sales", "SP Showroom Cashier", "SP Winch Manager"),
	"finance": ("SP Accountant", *ADMIN),
	"compliance": ("SP Regulatory Compliance", *ADMIN),
}


@dataclass(frozen=True)
class Card:
	key: str
	label: str
	variants: tuple[str, ...]
	fn: Callable


CARDS: dict[str, Card] = {}


def card(key: str, label: str, variants: tuple[str, ...]):
	"""Register a home card; its function returns value / fieldtype / indicator / note / route."""

	def register(fn):
		CARDS[key] = Card(key, label, variants, fn)
		return fn

	return register


def variants_of_roles(roles) -> list[str]:
	roles = set(roles)
	return [v for v, v_roles in VARIANTS.items() if roles & set(v_roles)]


def variants_of(user: str) -> list[str]:
	if user == "Administrator":
		return list(VARIANTS)
	return variants_of_roles(frappe.get_roles(user))


@frappe.whitelist()
def get_home() -> dict:
	"""The signed-in user's cards, in the order they were registered (cached a minute)."""
	user = frappe.session.user
	key = f"sp_home_cards:{user}"
	cached = frappe.cache.get_value(key)
	if cached:
		return cached
	variants = variants_of(user)
	home = frappe.db.get_value("User", user, "sp_home_page") if user != "Administrator" else None
	if home in variants:  # the home the admin chose for this user comes first (X1, SP-130)
		variants = [home] + [v for v in variants if v != home]
	cards = []
	for c in CARDS.values():
		if not set(c.variants) & set(variants):
			continue
		data = c.fn(user)
		if data is None:  # a card that does not apply to this person (e.g. no cash account)
			continue
		cards.append({"key": c.key, "label": _(c.label), "fieldtype": INT, "indicator": GRAY, **data})
	if home in variants:
		cards.sort(key=lambda card: home not in CARDS[card["key"]].variants)
	result = {"variants": variants, "cards": cards, "home": home if home in variants else None}
	frappe.cache.set_value(key, result, expires_in_sec=CACHE_SECONDS)
	return result


def _list(doctype: str, **filters) -> dict:
	"""Where a click goes: the doctype's list with the card's filter."""
	return {"route": ["List", doctype], "route_options": filters}


def _hours_since(value) -> float:
	return max((now_datetime() - get_datetime(value)).total_seconds(), 0) / SECONDS_PER_HOUR


# --- technical office --------------------------------------------------------------------------


@card("requests_waiting", "Requests waiting", ("tech_office",))
def requests_waiting(user: str) -> dict:
	"""Open quote requests not taken, or taken by me, with no quote sent: the count and the oldest;
	red once the oldest is past the quote clock (24 h)."""
	from smart_power.sp_sales.quote_clock import due_hours

	rows = frappe.db.sql(
		"""select creation from `tabSP Case`
		where status in ('Quote request', 'Draft') and ifnull(quote_sent_at, '') = ''
			and (ifnull(quote_creator, '') = '' and status = 'Quote request' or quote_creator = %s)
		order by creation asc""",
		user,
	)
	count = len(rows)
	oldest = round(_hours_since(rows[0][0])) if rows else 0
	limit = due_hours()
	return {
		"value": count,
		"indicator": RED if count and limit and oldest >= limit else (ORANGE if count else GREEN),
		"note": _("Oldest: {0} h").format(oldest) if count else "",
		"route": ["sp-quote-queue"],
	}


# --- showroom: the cash I hold ------------------------------------------------------------------


@card("cash_on_hand", "Cash on hand", ("showroom", "intake", "finance"))
def cash_on_hand(user: str) -> dict | None:
	"""My transit (cash) balance and how many days the oldest of it is held; red past the limit."""
	from smart_power.sp_finance.accounts import my_balances

	rows = [r for r in my_balances() if r["sp_account_kind"] == "Transit"]  # the signed-in user's
	if not rows:
		return None
	balance = sum(flt(r["balance"]) for r in rows)
	held = max(r["days_held"] for r in rows)
	over = any(r["over"] for r in rows)
	return {
		"value": balance,
		"fieldtype": CURRENCY,
		"indicator": RED if over else (ORANGE if balance else GREEN),
		"note": _("{0} days held").format(held) if balance else "",
		"route": ["sp-profile"],
	}


# --- intake / follow-up --------------------------------------------------------------------------


@card("my_requests_waiting", "My requests waiting for a quote", ("intake", "marketing"))
def my_requests_waiting(user: str) -> dict:
	"""The requests I brought in that still wait for a quote (the same filter as the list it opens)."""
	from smart_power.sp_sales.quote_clock import due_hours

	rows = frappe.db.sql(
		"""select creation from `tabSP Case`
		where status in ('Quote request', 'Draft') and ifnull(quote_sent_at, '') = ''
			and requested_by = %s order by creation asc""",
		user,
	)
	oldest = round(_hours_since(rows[0][0])) if rows else 0
	limit = due_hours()
	return {
		"value": len(rows),
		"indicator": RED if rows and limit and oldest >= limit else (ORANGE if rows else GREEN),
		"note": _("Oldest: {0} h").format(oldest) if rows else "",
		**_list("SP Case", status=["in", ["Quote request", "Draft"]], requested_by=user),
	}


@card("calls_due_today", "Calls due today", ("intake",))
def calls_due_today(user: str) -> dict:
	end = f"{nowdate()} 23:59:59"
	count = frappe.db.count(
		"SP Task",
		{
			"task_type": "Follow-up Call",
			"status": "Open",
			"assigned_to": user,
			"due_at": ("between", [nowdate(), end]),
		},
	)
	return {
		"value": count,
		"indicator": ORANGE if count else GREEN,
		**_list("SP Task", task_type="Follow-up Call", status="Open", assigned_to=user),
	}


@card("overdue_callbacks", "Overdue call-backs", ("intake",))
def overdue_callbacks(user: str) -> dict:
	count = frappe.db.count(
		"SP Task",
		{
			"task_type": "Follow-up Call",
			"status": "Open",
			"assigned_to": user,
			"due_at": ("<", now_datetime()),
		},
	)
	return {
		"value": count,
		"indicator": RED if count else GREEN,
		**_list("SP Task", task_type="Follow-up Call", status="Open", assigned_to=user),
	}


@card("quotes_expiring", "Quotes expiring in 48 h", ("intake",))
def quotes_expiring(user: str) -> dict:
	soon = add_days(getdate(nowdate()), 2)  # sp-allow-number: the story's 48 hours
	count = frappe.db.sql(
		"""select count(*) from `tabQuotation` q join `tabSP Case` c on c.name = q.sp_case
		where q.docstatus = 1 and q.sp_status = 'Sent' and q.valid_till between %s and %s
			and (c.requested_by = %s or c.follow_up_owner = %s)""",
		(nowdate(), soon, user, user),
	)[0][0]
	return {
		"value": count,
		"indicator": ORANGE if count else GREEN,
		**_list("Quotation", sp_status="Sent", valid_till=["between", [nowdate(), str(soon)]]),
	}


@card("documents_expiring", "Documents expiring", ("compliance",))
def documents_expiring(user: str) -> dict:
	"""The qualification documents expired or inside their first reminder mark (RG1, SP-101): red
	once one has expired."""
	from smart_power.sp_stations.compliance import DOCUMENT, expiring_filter

	soon = expiring_filter()
	count = frappe.db.count(DOCUMENT, {"expiry_date": soon})
	expired = frappe.db.count(DOCUMENT, {"expiry_date": ("<", nowdate())})
	return {
		"value": count,
		"indicator": RED if expired else ORANGE if count else GREEN,
		"note": _("{0} expired").format(expired) if expired else "",
		**_list(DOCUMENT, expiry_date=soon),
	}


def _month_start() -> str:
	return str(getdate(nowdate()).replace(day=1))


def _today_range() -> list[str]:
	return [nowdate(), f"{nowdate()} 23:59:59"]


def _count(doctype: str, filters: dict, indicator_if_any: str = ORANGE, **route) -> dict:
	"""A plain count card: the list behind it uses the same filters."""
	count = frappe.db.count(doctype, filters)
	return {
		"value": count,
		"indicator": indicator_if_any if count else GREEN,
		**_list(doctype, **(route or filters)),
	}


def _sum(doctype: str, field: str, filters: dict) -> float:
	return sum(flt(v) for v in frappe.get_all(doctype, filters=filters, pluck=field))


EVERYONE_WITH_ACCOUNTS = tuple(VARIANTS)


# --- intake / follow-up (more) -----------------------------------------------------------------


@card("quotes_received_today", "Quotes received today", ("intake",))
def quotes_received_today(user: str) -> dict:
	filters = {"requested_by": user, "quote_sent_at": ("between", _today_range())}
	data = _count("SP Case", filters, GREEN)
	data["indicator"] = GREEN if data["value"] else GRAY
	return data


@card("my_collections_month", "My collections this month", ("intake", "showroom"))
def my_collections_month(user: str) -> dict:
	filters = {"recorded_by": user, "status": "Confirmed", "work_date": (">=", _month_start())}
	return {
		"value": _sum("SP Customer Payment", "amount", filters),
		"fieldtype": CURRENCY,
		"indicator": GRAY,
		**_list(
			"SP Customer Payment", recorded_by=user, status="Confirmed", work_date=[">=", _month_start()]
		),
	}


# --- marketing ---------------------------------------------------------------------------------


@card("my_leads_week", "My new leads this week", ("marketing",))
def my_leads_week(user: str) -> dict:
	since = str(add_days(getdate(nowdate()), -6))  # sp-allow-number: the last 7 days
	filters = {"requested_by": user, "creation": (">=", since)}
	data = _count("SP Case", filters, GREEN, requested_by=user, creation=[">=", since])
	data["indicator"] = GREEN if data["value"] else GRAY
	return data


@card("my_leads_waiting", "My leads with no request after 24 h", ("marketing",))
def my_leads_waiting(user: str) -> dict:
	from smart_power.sp_sales.leads import waiting_filters

	return _count("Lead", waiting_filters(user), ORANGE)


@card("my_won", "My won cases", ("marketing",))
def my_won(user: str) -> dict:
	data = _count("SP Case", {"requested_by": user, "status": "Won"}, GREEN)
	data["indicator"] = GREEN if data["value"] else GRAY
	return data


# --- technical office (more) -----------------------------------------------------------------


@card("quotes_sent_today", "Quotes sent today", ("tech_office",))
def quotes_sent_today(user: str) -> dict:
	filters = {"quote_creator": user, "quote_sent_at": ("between", _today_range())}
	data = _count("SP Case", filters, GREEN)
	data["indicator"] = GREEN if data["value"] else GRAY
	return data


# --- projects ----------------------------------------------------------------------------------


@card("waiting_contract", "Approved, waiting for the contract", ("projects",))
def waiting_contract(user: str) -> dict:
	filters = {"accepted_quotation": ("is", "set"), "status": ("not in", ["Won", "Lost"])}
	return _count(
		"SP Case", filters, ORANGE, accepted_quotation=["is", "set"], status=["not in", ["Won", "Lost"]]
	)


@card("open_stations", "Open stations", ("projects", "installations"))
def open_stations(user: str) -> dict:
	closed = ["Financially closed", "Cancelled"]
	from collections import Counter

	by_status = Counter(frappe.get_all("SP Station", filters={"status": ("not in", closed)}, pluck="status"))
	return {
		"value": sum(by_status.values()),
		"indicator": GRAY,
		"note": " · ".join(f"{_(status)} {n}" for status, n in by_status.items()),
		**_list("SP Station", status=["not in", closed]),
	}


@card("overdue_installments", "Stations with overdue instalments", ("projects", "finance"))
def overdue_installments(user: str) -> dict:
	return _count("SP Station", {"has_overdue": 1}, RED)


@card("cheques_due", "Cheques due", ("projects", "finance"))
def cheques_due(user: str) -> dict:
	return _count("SP Cheque", {"status": "Due"}, ORANGE)


# --- installations -----------------------------------------------------------------------------


@card("deliveries_due_week", "Deliveries due this week", ("projects",))
def deliveries_due_week(user: str) -> dict:
	"""Open purchase orders whose next batch is due within a week; orange while any is late."""
	week = add_days(getdate(nowdate()), 7)  # sp-allow-number: the story's week
	open_orders = {"sp_status": ("in", ("Sent", "Partly received"))}
	count = frappe.db.count(
		"Purchase Order", {**open_orders, "sp_next_delivery": ("between", (nowdate(), str(week)))}
	)
	late = frappe.db.count("Purchase Order", {**open_orders, "sp_next_delivery": ("<", nowdate())})
	return {
		"value": count,
		"indicator": ORANGE if late else (GREEN if not count else GRAY),
		"note": _("{0} late").format(late) if late else "",
		**_list(
			"Purchase Order",
			sp_status=["in", ["Sent", "Partly received"]],
			sp_next_delivery=["between", [nowdate(), str(week)]],
		),
	}


@card("survey_tasks", "Site survey tasks", ("installations",))
def survey_tasks(user: str) -> dict:
	return _count("SP Task", {"task_type": "Site Survey", "status": "Open", "assigned_to": user}, ORANGE)


@card("my_custody", "My custody", EVERYONE_WITH_ACCOUNTS)
def my_custody(user: str) -> dict | None:
	"""What is left of the custody I hold; only for someone who holds one."""
	from smart_power.sp_finance.accounts import my_balances

	rows = [r for r in my_balances() if r["sp_account_kind"] == "Custody"]
	if not rows:
		return None
	return {
		"value": sum(flt(r["balance"]) for r in rows),
		"fieldtype": CURRENCY,
		"indicator": GRAY,
		"route": ["sp-my-custody"],
	}


# --- store -------------------------------------------------------------------------------------


@card("consignment_low", "Consignment containers running low", ("store",))
def consignment_low(user: str) -> dict:
	return _count("SP Consignment Container", {"status": "Low"}, ORANGE)


# --- showroom ----------------------------------------------------------------------------------


@card("payments_today", "Station payments today", ("showroom",))
def payments_today(user: str) -> dict:
	filters = {"recorded_by": user, "work_date": nowdate(), "docstatus": 1}
	return {
		"value": _sum("SP Customer Payment", "amount", filters),
		"fieldtype": CURRENCY,
		"indicator": GRAY,
		**_list("SP Customer Payment", recorded_by=user, work_date=nowdate()),
	}


# --- finance -----------------------------------------------------------------------------------


@card("waiting_confirmation", "Waiting for confirmation", ("finance",))
def waiting_confirmation(user: str) -> dict:
	"""Customer payments and money transfers the admin has not confirmed yet: count and amount."""
	pending = {"status": "Pending"}
	count = frappe.db.count("SP Customer Payment", pending) + frappe.db.count("SP Transfer", pending)
	amount = _sum("SP Customer Payment", "amount", pending) + _sum("SP Transfer", "amount", pending)
	return {
		"value": count,
		"indicator": ORANGE if count else GREEN,
		"note": frappe.format(amount, "Currency") if count else "",
		"route": ["sp-confirmations"],
	}


@card("period_status", "Months not closed", ("finance",))
def period_status(user: str) -> dict:
	"""A14 (SP-126): the ended months still open, and how the last one stands."""
	from smart_power.sp_finance.month_close import period_status as status

	s = status()
	month = getdate(s["month"]).strftime("%m-%Y")
	return {
		"value": s["open_months"],
		"indicator": GREEN if s["closed"] else ORANGE,
		"note": _("{0}: closed").format(month) if s["closed"] else _("{0}: open").format(month),
		"route": ["sp-month-end"],
	}


@card("cash_in_transit", "Cash in transit (all holders)", ("finance",))
def cash_in_transit(user: str) -> dict:
	from erpnext.accounts.utils import get_balance_on

	from smart_power.sp_finance.transit import transit_accounts

	total = sum(
		flt(get_balance_on(a.name, company=a.company, ignore_account_permission=True))
		for a in transit_accounts()
	)
	return {
		"value": total,
		"fieldtype": CURRENCY,
		"indicator": ORANGE if total else GREEN,
		"route": ["sp-treasury"],
	}


@card("entries_locking", "Entries locking in 24 h", ("projects", "showroom"))
def entries_locking(user: str) -> dict | None:
	"""Field entries whose last open day is today (SP-109), for who follows the winch and Jumbo."""
	if not frappe.has_permission("SP Field Entry", "read", user=user):
		return None
	from smart_power.sp_winch.field_lock import locking_soon

	names = locking_soon(user)
	return {
		"value": len(names),
		"indicator": ORANGE if names else GREEN,
		**_list("SP Field Entry", name=["in", names]),
	}


@card("showroom_stock_low", "Showroom stock low", ("showroom", "store"))
def showroom_stock_low(user: str) -> dict | None:
	"""Items of the showroom store at or under their reorder level (SP-87)."""
	if not frappe.has_permission("Bin", "read", user=user):
		return None
	from smart_power.sp_stock.showroom_stock import REPORT, low_items, showroom_stores

	rows = low_items()
	stores = showroom_stores()
	return {
		"value": len(rows),
		"indicator": RED if rows else GREEN,
		"route": ["query-report", REPORT],
		"route_options": {"below_reorder": 1, **({"location": stores[0]} if len(stores) == 1 else {})},
	}


@card("next_stock_count", "Next Stock Count", ("store", "showroom"))
def next_stock_count(user: str) -> dict | None:
	"""Days to the next scheduled count of my locations; 0 and orange while a sheet is open (SP-94)."""
	from frappe.utils import date_diff, nowdate

	from smart_power.sp_stock.stock_count import next_counts

	rows = next_counts(user)
	if not rows:
		return None
	first = rows[0]
	days = max(date_diff(first["due"], nowdate()), 0)
	return {
		"value": days,
		"indicator": ORANGE if days == 0 else GREEN,
		"note": f"{first['warehouse']} · {frappe.utils.formatdate(first['due'])}",
		"route": ["sp-count-sheets", first["open"]] if first["open"] else ["sp-count-sheets"],
	}


@card("consignment_reco_due", "Consignment reconciliation due", ("store",))
def consignment_reco_due(user: str) -> dict | None:
	"""Monthly reconciliation sheets still waiting for the supplier's statement (SP-93)."""
	from smart_power.sp_stock.consignment_reconciliation import (
		DRAFT,
		RECONCILIATION,
		_can_reconcile,
		due_count,
	)

	if not _can_reconcile(user):
		return None
	count = due_count(user)
	return {
		"value": count,
		"indicator": ORANGE if count else GREEN,
		"route": ["List", RECONCILIATION],
		"route_options": {"status": DRAFT},
	}


@card("supplier_dues_week", "Supplier dues this week", ("finance",))
def supplier_dues_week(user: str) -> dict:
	"""What suppliers are owed within a week; orange while any of it is late (SP-86)."""
	from smart_power.sp_finance.supplier_ledger import dues_this_week

	dues = dues_this_week()
	return {
		"value": dues["amount"],
		"fieldtype": CURRENCY,
		"indicator": ORANGE if dues["overdue"] else GRAY,
		"note": _("{0} late").format(frappe.format(dues["overdue"], "Currency")) if dues["overdue"] else "",
		**_list(
			"Purchase Invoice",
			docstatus=1,
			outstanding_amount=[">", 0],
			due_date=["<=", dues["week_end"]],
		),
	}


@card("bounced_cheques", "Bounced cheques", ("finance",))
def bounced_cheques(user: str) -> dict:
	return _count("SP Cheque", {"status": "Bounced"}, RED)


@card("settlements_pending", "Custody settlements to approve", ("finance",))
def settlements_pending(user: str) -> dict:
	return _count("SP Custody Settlement", {"status": "Pending"}, ORANGE)
