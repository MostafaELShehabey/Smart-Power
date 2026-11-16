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


def variants_of(user: str) -> list[str]:
	if user == "Administrator":
		return list(VARIANTS)
	roles = set(frappe.get_roles(user))
	return [v for v, v_roles in VARIANTS.items() if roles & set(v_roles)]


@frappe.whitelist()
def get_home() -> dict:
	"""The signed-in user's cards, in the order they were registered (cached a minute)."""
	user = frappe.session.user
	key = f"sp_home_cards:{user}"
	cached = frappe.cache.get_value(key)
	if cached:
		return cached
	variants = variants_of(user)
	cards = []
	for c in CARDS.values():
		if not set(c.variants) & set(variants):
			continue
		data = c.fn(user)
		if data is None:  # a card that does not apply to this person (e.g. no cash account)
			continue
		cards.append({"key": c.key, "label": _(c.label), "fieldtype": INT, "indicator": GRAY, **data})
	result = {"variants": variants, "cards": cards}
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
