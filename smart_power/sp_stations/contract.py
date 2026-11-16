"""The contract is a Sales Order made from the approved quote version (SP-74; decisions 39, 55,
58, 59; tech plan 6-11-2026 section 3 rule 8).

Stock reservations and purchase orders from the order need a Sales Order, so it exists from the
deposit. Whether a deposit can come before the contract is still open, so both paths work:

    make_contract(case)                    the project manager, when the contract is signed first
    make_contract(case, at_deposit=True)   the deposit automation (SP-175)

It is idempotent: a case never gets a second Sales Order; the deposit reuses the one already
made and freezes the station's estimated cost then. The order is built from the approved
version, whichever option it is (SP-59: approve B and the order is B). The case's station is
opened with it when it has none, and the order, the station and its project link one-to-one.
The payment schedule comes from the quote and is completed by hand in R1 (the instalment
generator is SP-60, R2); postal cheques and the referrer's lump sum sit on the order.
"""

import json

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.utils import flt, getdate, now_datetime, today

from smart_power.sp_quotes.special_lines import COMMISSION, WINCH, kind_total

CASE, SO, STATION, QUOTE = "SP Case", "Sales Order", "SP Station", "Quotation"
WINCH_EXPECTED, WINCH_DONE = "Expected", "Done"
# the contracts role (Sales User underneath): أميرة holds it in the Projects Manager profile
CONTRACT_ROLES = ("SP Contract Manager", "SP Admin", "System Manager")


def contract_of(case: str) -> str | None:
	"""The case's Sales Order, if it has one (a cancelled one does not count)."""
	return frappe.db.get_value(SO, {"sp_case": case, "docstatus": ("<", DocStatus.cancelled())}, "name")


def _check_can_contract() -> None:
	if frappe.session.user != "Administrator" and not set(CONTRACT_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the contracts manager or the admin makes the contract."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def make_contract(case: str, at_deposit: bool = False) -> dict:
	"""The case's contract (Sales Order) and station, made once; at the deposit the estimate is
	frozen. Returns {sales_order, station, created}."""
	_check_can_contract()
	return ensure_contract(case, at_deposit=frappe.utils.cint(at_deposit))


def ensure_contract(case: str, at_deposit: bool = False) -> dict:
	"""make_contract without the role check, for the deposit automation (SP-175)."""
	doc = frappe.get_doc(CASE, case)
	so_name, created = contract_of(case), False
	if not so_name:
		if not doc.accepted_quotation:
			frappe.throw(
				_(
					"Case {0} has no approved quote version. Approve the version the customer accepted first."
				).format(case)
			)
		so_name, created = _build_order(doc).name, True
	station = _station_for(doc, so_name)
	_link(so_name, station)
	_carry_special_lines(so_name, station, doc.accepted_quotation)
	if at_deposit:
		freeze_estimate(so_name)
	from smart_power.sp_stations.money import refresh

	refresh(station)
	return {"sales_order": so_name, "station": station, "created": created}


def _build_order(case):
	from erpnext.selling.doctype.quotation.quotation import _make_sales_order

	quote = frappe.get_doc(QUOTE, case.accepted_quotation)
	# the approved version may have passed its validity by the time the contract is signed
	so = _make_sales_order(quote.name, ignore_permissions=True)
	so.sp_case = case.name
	so.transaction_date = today()
	so.delivery_date = so.delivery_date or today()
	from smart_power.sp_stock.warehouses import MAIN, warehouse_of

	# the stock is reserved and delivered from the company's main store (SP-28)
	main = warehouse_of(so.company, MAIN)
	if main:
		so.set_warehouse = main
	for row in so.items:
		row.delivery_date = row.delivery_date or so.delivery_date
		if main:
			row.warehouse = main
	# the commission is cost only: it goes to the contract as the station's commission (SP-58)
	commission = {r.name for r in quote.items if r.get("sp_line_kind") == COMMISSION}
	if commission:
		so.set("items", [r for r in so.items if r.get("quotation_item") not in commission])
		so.sp_referrer_commission = flt(so.get("sp_referrer_commission")) or kind_total(
			quote, COMMISSION, cost=True
		)
	warranty = {r.name: r.get("sp_warranty_years") for r in quote.items}
	for row in so.items:
		if row.get("quotation_item") in warranty:
			row.sp_warranty_years = warranty[row.quotation_item]
	if not so.get("payment_schedule") and quote.get("payment_schedule"):
		for row in quote.payment_schedule:
			so.append(
				"payment_schedule",
				{
					"due_date": max(getdate(row.due_date), getdate(so.transaction_date))
					if row.due_date
					else so.transaction_date,
					"invoice_portion": row.invoice_portion,
					"payment_amount": row.payment_amount,
					"description": row.get("description"),
				},
			)
	so.flags.ignore_permissions = True
	so.insert()
	return so


def _station_for(case, so_name: str) -> str:
	station = frappe.db.get_value(STATION, {"case": case.name, "status": ("!=", "Cancelled")})
	if station:
		return station
	so = frappe.get_doc(SO, so_name)
	doc = frappe.get_doc(
		{
			"doctype": STATION,
			"case": case.name,
			"company": so.company,
			"quotation_accepted": case.accepted_quotation,
			"financing_type": so.get("sp_financing_type"),
			"bank_branch": so.get("sp_bank_branch"),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _carry_special_lines(so_name: str, station: str, quote: str | None) -> None:
	"""The quote's winch line becomes the station's expected winch job; its commission the
	station's commission (SP-58). A job already done is left as it is."""
	if not quote:
		return
	quote = frappe.get_doc(QUOTE, quote)
	values = {}
	winch = kind_total(quote, WINCH)
	if winch and frappe.db.get_value(STATION, station, "winch_status") != WINCH_DONE:
		values.update(winch_expected_amount=winch, winch_status=WINCH_EXPECTED)
	commission = flt(frappe.db.get_value(SO, so_name, "sp_referrer_commission"))
	if commission and not flt(frappe.db.get_value(STATION, station, "commission_amount")):
		values["commission_amount"] = commission
	if values:
		frappe.db.set_value(STATION, station, values, update_modified=False)


def _link(so_name: str, station: str) -> None:
	"""Order ↔ station ↔ project, one to one."""
	project = frappe.db.get_value(STATION, station, "project")
	other = frappe.db.get_value(STATION, {"sales_order": so_name, "name": ("!=", station)})
	if other:
		frappe.throw(_("Sales Order {0} already belongs to station {1}.").format(so_name, other))
	frappe.db.set_value(
		STATION, station, {"sales_order": so_name, "contract_date": today()}, update_modified=False
	)
	frappe.db.set_value(SO, so_name, {"sp_station": station, "project": project}, update_modified=False)
	if project:
		for row in frappe.get_all("Sales Order Item", {"parent": so_name}, pluck="name"):
			frappe.db.set_value("Sales Order Item", row, "project", project, update_modified=False)


def freeze_estimate(so_name: str) -> bool:
	"""At the deposit: the station keeps the estimated cost of the approved lines, once."""
	so = frappe.get_doc(SO, so_name)
	if so.get("sp_estimate_frozen_on"):
		return False
	quote = so.items[0].get("prevdoc_docname") if so.items else None
	rows = frappe.get_doc(QUOTE, quote).items if quote else []
	lines = [
		{"item_code": r.item_code, "qty": flt(r.qty), "rate": flt(r.rate), "cost": flt(r.get("sp_cost"))}
		for r in rows
	]
	snapshot = {
		"frozen_on": str(now_datetime()),
		"lines": lines,
		"total_cost": sum(line["cost"] * line["qty"] for line in lines),
	}
	frappe.db.set_value(SO, so_name, "sp_estimate_frozen_on", now_datetime(), update_modified=False)
	if so.get("sp_station"):
		frappe.db.set_value(
			STATION, so.sp_station, "estimated_cost_snapshot", json.dumps(snapshot), update_modified=False
		)
	return True


def on_order_change(doc, method=None) -> None:
	"""Sales Order on_update / on_submit / on_cancel: the station's money follows the contract."""
	from smart_power.sp_stations.money import refresh

	if doc.get("sp_station") and frappe.db.exists(STATION, doc.sp_station):
		refresh(doc.sp_station)


def validate_order(doc, method=None) -> None:
	"""Sales Order validate: one order per case; the referrer's lump sum follows the station."""
	if not doc.get("sp_case"):
		return
	other = frappe.db.get_value(
		SO,
		{"sp_case": doc.sp_case, "docstatus": ("<", DocStatus.cancelled()), "name": ("!=", doc.name)},
		"name",
	)
	if other:
		frappe.throw(_("Case {0} already has the contract {1}.").format(doc.sp_case, other))
	if doc.get("sp_station") and not doc.is_new():
		frappe.db.set_value(
			STATION,
			doc.sp_station,
			{
				"commission_amount": flt(doc.get("sp_referrer_commission")),
				# the financing chosen on the contract (an Agri Bank advance follows it, SP-121)
				"financing_type": doc.get("sp_financing_type"),
				"bank_branch": doc.get("sp_bank_branch"),
			},
			update_modified=False,
		)


@frappe.whitelist()
def contract_info(case: str) -> dict:
	"""For the case and station forms: the contract, the station, and whether this user may make it."""
	doc = frappe.get_doc(CASE, case)
	doc.check_permission("read")
	can_make = frappe.session.user == "Administrator" or bool(set(CONTRACT_ROLES) & set(frappe.get_roles()))
	return {
		"sales_order": contract_of(case),
		"station": frappe.db.get_value(STATION, {"case": case, "status": ("!=", "Cancelled")}),
		"approved": doc.accepted_quotation,
		"can_make": can_make and doc.status != "Lost",
	}
