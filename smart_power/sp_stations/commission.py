"""The referrer's commission (SP-177; decisions 5, 42, 59 and 74).

A referrer is an ERPNext Sales Partner, registered with full name and a unique mobile. The admin
or the contracts manager sets it on the station (owner, 2026-11-21); the contract takes it.

The agreed lump sum is the quote's hidden commission line (SP-58): it is part of the cost, never
printed, and moves to the contract (sp_referrer_commission) and the station (commission_amount),
where the Costs tab counts it (SP-76).

At the commission event (Smart Power Settings, Post Referrer Commission At: Deposit by default
(owner, 2026-11-21), Technical close or Manual) a Journal Entry posts it through the Account Map
event "Referrer Commission": the expense on the station's project, a payable to the referrer
(party type Sales Partner). It posts once per station. The referrer is paid with a normal
Payment Entry (Pay, party type Sales Partner).

    post_commission(station)          the admin's Post Commission button (any event)
    at(event, station)                the deposit and the technical close call it
    referrers(filters)                the report's rows: agreed, posted, paid, balance
"""

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.sp_stations.station import is_admin

STATION, JE, ENTRY, PARTNER, PARTY_TYPE = (
	"SP Station",
	"Journal Entry",
	"Payment Entry",
	"Sales Partner",
	"Party Type",
)
EVENT = "Referrer Commission"
DEPOSIT, TECH_CLOSE, MANUAL = "Deposit", "Technical close", "Manual"
EXPENSE_ACCOUNT, PAYABLE_ACCOUNT = "Referrer Commissions", "Referrer Commissions Payable"
ADMIN_ROLE, REFERRER_TASK = "SP Admin", "Set Referrer"


# --- setup ------------------------------------------------------------------------------------------


def ensure_party_type() -> None:
	"""A Sales Partner can be owed money and paid (ERPNext's Party Type)."""
	if not frappe.db.exists(PARTY_TYPE, PARTNER):
		frappe.get_doc({"doctype": PARTY_TYPE, "party_type": PARTNER, "account_type": "Payable"}).insert(
			ignore_permissions=True
		)


def _account(company: str, account_name: str) -> str | None:
	return frappe.db.get_value("Account", {"company": company, "account_name": account_name, "is_group": 0})


def seed_account_map(company: str) -> None:
	"""The Referrer Commission row of the Account Map, once. The admin can change it."""
	from smart_power.constants import SETTINGS_DOCTYPE

	ensure_party_type()
	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if any(r.event == EVENT for r in settings.account_map):
		return
	expense, payable = _account(company, EXPENSE_ACCOUNT), _account(company, PAYABLE_ACCOUNT)
	center = frappe.get_cached_value("Company", company, "cost_center")
	if not (expense and payable and center):
		return
	settings.append(
		"account_map",
		{
			"event": EVENT,
			"debit_account": expense,
			"debit_center_rule": "From document",
			"debit_cost_center": center,
			"credit_account": payable,
			"credit_center_rule": "From document",
			"credit_cost_center": center,
			"project_rule": "Debit side",
			"note": "A station's referrer commission: the expense on the station, owed to the referrer.",
		},
	)
	settings.flags.ignore_permissions = True
	settings.save()


# --- the referrer on the station and the contract ------------------------------------------------


def sync_referrer(doc) -> None:
	"""SP Station validate: the contract names the station's referrer (Sales Order sales_partner)."""
	if doc.sales_order and doc.has_value_changed("sales_partner"):
		frappe.db.set_value(
			"Sales Order", doc.sales_order, "sales_partner", doc.sales_partner, update_modified=False
		)


# --- posting ----------------------------------------------------------------------------------------


def posted(station: str) -> str | None:
	return frappe.db.get_value(
		JE,
		{"sp_source_doctype": STATION, "sp_source_name": station, "sp_posting_event": EVENT, "docstatus": 1},
	)


def event_setting() -> str:
	from smart_power.sp_core.services.settings import get_value

	return get_value("referrer_commission_event") or DEPOSIT


def _post(doc) -> str | None:
	"""Post the station's commission once; None when there is nothing (or no one) to post to."""
	from smart_power.sp_finance.posting import post

	amount = flt(doc.commission_amount)
	if amount <= 0 or posted(doc.name):
		return None
	if not doc.sales_partner:
		_ask_for_referrer(doc)
		return None
	from smart_power.sp_core.inbox import close_tasks

	frappe.flags.sp_system_posting = True  # the posting is the system's (SP-26)
	try:
		entry = post(
			EVENT,
			doc,
			amount,
			project=doc.project,
			party_type=PARTNER,
			party=doc.sales_partner,
			remark=_("Referrer commission of station {0} to {1}").format(doc.name, doc.sales_partner),
		)
	finally:
		frappe.flags.sp_system_posting = False
	close_tasks(STATION, doc.name, REFERRER_TASK)  # the referrer is set and the commission posted
	return entry


def _ask_for_referrer(doc) -> None:
	from smart_power.sp_core.inbox import create_task
	from smart_power.sp_sales.quote_request import _users_with

	create_task(
		REFERRER_TASK,
		STATION,
		doc.name,
		_users_with(ADMIN_ROLE) or ["Administrator"],
		_(
			"Station {0} has a referrer commission of {1} but no referrer: set it to post the commission"
		).format(doc.name, frappe.format(doc.commission_amount, "Currency")),
	)


def at(event: str, station) -> str | None:
	"""The deposit or the technical close: post when the setting names this event."""
	if event_setting() != event:
		return None
	doc = frappe.get_doc(STATION, station) if isinstance(station, str) else station
	return _post(doc)


def on_station_update(doc, method=None) -> None:
	"""SP Station on_update: the technical close may be the commission event."""
	from smart_power.sp_stations.station_workflow import TECH_CLOSED

	if doc.has_value_changed("status") and doc.status == TECH_CLOSED:
		at(TECH_CLOSE, doc)


@frappe.whitelist(methods=["POST"])
def post_commission(station: str) -> str:
	"""The admin posts the commission now (the Manual setting, or one the event did not post)."""
	if not is_admin():
		frappe.throw(_("Only the admin posts a referrer commission."), frappe.PermissionError)
	doc = frappe.get_doc(STATION, station)
	if posted(doc.name):
		frappe.throw(_("The commission of station {0} is already posted.").format(doc.name))
	if flt(doc.commission_amount) <= 0:
		frappe.throw(_("Station {0} has no referrer commission.").format(doc.name))
	if not doc.sales_partner:
		frappe.throw(_("Set the station's referrer first."), frappe.MandatoryError)
	return _post(doc)


@frappe.whitelist()
def commission_state(station: str) -> dict:
	"""For the station form's Post Commission button."""
	doc = frappe.get_doc(STATION, station)
	doc.check_permission("read")
	return {"posted": posted(doc.name), "event": event_setting(), "can_post": is_admin()}


# --- the report -------------------------------------------------------------------------------------


def referrers(filters: dict | None = None) -> list[dict]:
	"""Per referrer: stations, the agreed commission, what is posted, what is paid, the balance."""
	filters = frappe._dict(filters or {})
	partner_filter = {"name": filters.referrer} if filters.get("referrer") else {}
	partners = frappe.get_all(
		PARTNER, partner_filter, ["name", "partner_name", "sp_mobile"], order_by="name asc"
	)
	rows = []
	for p in partners:
		stations = frappe.get_all(
			STATION,
			{"sales_partner": p.name, "status": ("!=", "Cancelled")},
			["name", "commission_amount"],
		)
		posted_amount = sum(
			flt(r.credit) - flt(r.debit)
			for r in frappe.get_all(
				"GL Entry",
				{"party_type": PARTNER, "party": p.name, "is_cancelled": 0, "voucher_type": JE},
				["debit", "credit"],
			)
		)
		paid = sum(
			flt(v)
			for v in frappe.get_all(
				ENTRY,
				{"party_type": PARTNER, "party": p.name, "docstatus": 1, "payment_type": "Pay"},
				pluck="paid_amount",
			)
		)
		agreed = sum(flt(s.commission_amount) for s in stations)
		if not (stations or posted_amount or paid):
			continue
		rows.append(
			{
				"referrer": p.name,
				"referrer_name": p.partner_name,
				"mobile": p.sp_mobile,
				"stations": len(stations),
				"agreed": agreed,
				"posted": posted_amount,
				"paid": paid,
				"balance": posted_amount - paid,
				"not_posted": max(agreed - posted_amount, 0.0),
			}
		)
	return rows
