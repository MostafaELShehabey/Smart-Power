"""SH5 Payment on a station at the showroom (SP-103).

The showroom cashier takes a station customer's instalment at the showroom. It is credited to
that station's customer, never to showroom sales: it is an SP Customer Payment (SP-114) with
channel Showroom, pending the admin's confirmation (A1). Cash goes into the showroom box
(خزنة المعرض, Showroom Safe) until it is deposited; other methods go to an official account with
the receipt photo. The collection owner is told at once.

    find_station(q)   the stations of a customer, by name, mobile or station number: what is
                      still owed and the schedule (sale-price data only, nothing of costs)
    options()         the methods, the showroom box and the official accounts
    record(values)    record and submit the payment: pending confirmation
    today()           the payments taken at the showroom today

The SP Customer Payment DocType is kept although the 8-11-2026 note asked for a draft Payment
Entry: SP-114 shipped it, and confirming it creates that Payment Entry on the station's project.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from smart_power.sp_finance.accounts import OFFICIAL
from smart_power.sp_finance.customer_payment import (
	CASH,
	PAYMENT,
	SHOWROOM,
	can_use_showroom_box,
	showroom_box_account,
)
from smart_power.sp_stations.installments import allocation

STATION = "SP Station"
OPEN_STATUSES = ("Open", "Purchasing", "Installing", "Technically closed")
RESULTS = 20  # sp-allow-number: stations listed for one search, a screen size
TODAY_SHOWN = 50  # sp-allow-number: today's showroom payments listed, a screen size
MIN_SEARCH = 3  # sp-allow-number: letters or digits before a search runs
TAKEN = ("station", "amount", "method", "receiving_account", "reference_no", "receipt_photo", "work_date")


def _check() -> None:
	if not can_use_showroom_box():
		frappe.throw(_("Only the showroom cashier takes station payments here."), frappe.PermissionError)


def _company() -> str | None:
	from erpnext import get_default_company

	return frappe.defaults.get_user_default("Company") or get_default_company()


def _station_row(name: str) -> dict:
	doc = frappe.get_doc(STATION, name)
	rows = allocation(doc)
	schedule = [
		{
			"due_date": r["due_date"],
			"amount": flt(r["payment_amount"]),
			"left": flt(r["left"]),
			"status": r["status"],
		}
		for r in rows
	]
	next_due = next((r for r in schedule if r["left"] > 0), None)
	return {
		"station": doc.name,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"status": doc.status,
		"remaining": max(flt(doc.remaining_amount) - flt(doc.pending_amount), 0.0),
		"pending": flt(doc.pending_amount),
		"next_due": next_due,
		"schedule": schedule,
	}


@frappe.whitelist()
def find_station(q: str) -> list[dict]:
	"""The open stations of a customer, found by name, mobile or station number."""
	_check()
	from smart_power.sp_sales.customer import normalize_mobile

	q = (q or "").strip()
	if len(q) < MIN_SEARCH:
		return []
	customers = set()
	mobile = normalize_mobile(q)
	if mobile and len(mobile) >= MIN_SEARCH:
		customers.update(frappe.get_all("Customer", {"sp_mobile": ("like", f"%{mobile}%")}, pluck="name"))
	names = frappe.get_all(
		STATION,
		filters={"status": ("in", OPEN_STATUSES)},
		or_filters={
			"name": ("like", f"%{q}%"),
			"customer_name": ("like", f"%{q}%"),
			"customer": ("in", list(customers) or [""]),
		},
		pluck="name",
		order_by="modified desc",
		limit=RESULTS,
	)
	return [_station_row(name) for name in names]


@frappe.whitelist()
def options() -> dict:
	_check()
	company = _company()
	arabic = frappe.local.lang == "ar"
	methods = frappe.get_all(
		"SP List Value",
		filters={"list_name": "Payment Method", "is_active": 1, "code": ("!=", "THIRD_PARTY")},
		fields=["name", "code", "value_ar", "value_en"],
		order_by="sort_order asc",
	)
	return {
		"company": company,
		"box": showroom_box_account(company),
		"cash": CASH,
		"methods": [
			{"name": m.name, "label": (m.value_ar if arabic else m.value_en) or m.value_ar or m.value_en}
			for m in methods
		],
		"accounts": frappe.get_all(
			"Account",
			{"company": company, "sp_account_kind": OFFICIAL, "is_group": 0, "disabled": 0},
			pluck="name",
			order_by="account_name",
		),
		"today": nowdate(),
	}


@frappe.whitelist(methods=["POST"])
def record(values: str | dict) -> str:
	"""Record the payment and submit it: it is pending the admin's confirmation."""
	_check()
	values = frappe.parse_json(values) or {}
	payment = {k: values.get(k) for k in TAKEN if values.get(k)}
	if not payment.get("station"):
		frappe.throw(_("Choose the station."), frappe.MandatoryError)
	if payment.get("method") == CASH or not payment.get("receiving_account"):
		payment["receiving_account"] = showroom_box_account(
			frappe.db.get_value(STATION, payment["station"], "company")
		)
	doc = frappe.get_doc({"doctype": PAYMENT, "channel": SHOWROOM, **payment})
	doc.insert()
	doc.submit()
	return doc.name


@frappe.whitelist()
def today() -> list[dict]:
	"""The station payments taken at the showroom today, with their status."""
	_check()
	return frappe.get_all(
		PAYMENT,
		filters={"channel": SHOWROOM, "work_date": nowdate()},
		fields=["name", "station", "customer_name", "amount", "method", "status", "recorded_by"],
		order_by="creation desc",
		limit=TODAY_SHOWN,
	)
