"""Close a station (SP-80; decisions 8, 9, 61, 72 and 73).

Technical close (the workflow's Close Technically, by the projects manager or the admin):
- needs the operation date and every station system commissioned, each component with its
  serial (owner, 2026-11-21: the nameplate photo comes with SP-179);
- the components' warranty runs from the operation date for the years on the approved quote's
  line of that item (the commissioning's own months when the quote has none); the warranty
  certificate prints them (SP Warranty Certificate);
- makes the final internal Sales Invoice from the contract: the approved version's prices plus
  the change orders, numbered SINV-.YYYY.-.#### (its own counter each year), the payments
  received set against it as advances. It is not printed or sent unless the bank or the
  customer asks; Frappe's Access Log keeps each print.

Financial close: when the station is technically closed and nothing remains (paid, or the rest
written off by the admin with a reason), it becomes Financially closed by itself; the workflow's
Close Financially does the same by hand. Either way a snapshot of the estimated and the actual
cost is stored (close_cost_snapshot).
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, today

from smart_power.sp_stations.station_workflow import FIN_CLOSED, TECH_CLOSED

STATION, SO, SI, COMMISSIONING = "SP Station", "Sales Order", "Sales Invoice", "SP Commissioning"
INVOICE_SERIES = "SINV-.YYYY.-.####"
REVENUE_ACCOUNT, WRITE_OFF_EVENT = "Projects Revenue", "Write-off"
MONTHS_PER_YEAR = 12  # sp-allow-number: a calendar fact
PENNY = 0.005  # sp-allow-number: half a piastre, rounding


# --- setup ------------------------------------------------------------------------------------------


def ensure_invoice_series(series: str = INVOICE_SERIES) -> None:
	"""Sales Invoice offers this yearly series (the final invoice's by default; SP-102 adds the
	showroom receipt's). The admin's other options are kept."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	field = frappe.get_meta(SI).get_field("naming_series")
	options = [o for o in (field.options or "").split("\n") if o.strip()] if field else []
	if series in options:
		return
	make_property_setter(
		SI,
		"naming_series",
		"options",
		"\n".join([*options, series]),
		"Text",
		validate_fields_for_doctype=False,
	)


def seed_account_map(company: str) -> None:
	"""The Write-off row of the Account Map, once: the company's own Write Off account against its
	receivable (the customer is the party), on the station's project. The admin can change it."""
	from smart_power.constants import SETTINGS_DOCTYPE

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if any(r.event == WRITE_OFF_EVENT for r in settings.account_map):
		return
	write_off, receivable, center = frappe.get_cached_value(
		"Company", company, ["write_off_account", "default_receivable_account", "cost_center"]
	)
	if not (write_off and receivable and center):
		return
	settings.append(
		"account_map",
		{
			"event": WRITE_OFF_EVENT,
			"debit_account": write_off,
			"debit_center_rule": "From document",
			"debit_cost_center": center,
			"credit_account": receivable,
			"credit_center_rule": "From document",
			"credit_cost_center": center,
			"project_rule": "Debit side",
			"note": "What the customer will not pay, written off by the admin with a reason (SP-80).",
		},
	)
	settings.flags.ignore_permissions = True
	settings.save()


# --- technical close ----------------------------------------------------------------------------------


def _commissionings(station: str) -> list:
	return frappe.get_all(COMMISSIONING, {"station": station, "docstatus": 1}, ["name", "system_row"])


def check_technical_close(doc) -> None:
	"""SP Station validate, on the way to Technically closed: what the close needs."""
	if not doc.operation_date:
		frappe.throw(
			_("Station {0} has no operation date: commission its systems first.").format(doc.name),
			title=_("Technical close"),
		)
	done = _commissionings(doc.name)
	missing_systems = [
		row.system_type or str(row.idx) for row in doc.systems if row.name not in {c.system_row for c in done}
	]
	if missing_systems or not done:
		frappe.throw(
			_("Commission every system before the technical close: {0}.").format(
				", ".join(_label(s) for s in missing_systems) or _("no system is commissioned")
			),
			title=_("Technical close"),
		)
	no_serial = frappe.get_all(
		"SP Station Component",
		{"parent": ("in", [c.name for c in done]), "parenttype": COMMISSIONING, "serial": ("in", ("", None))},
		["component_type", "item"],
	)
	if no_serial:
		frappe.throw(
			_("Fill in the serial of every component before the technical close: {0}.").format(
				", ".join(_(r.component_type) + (f" ({r.item})" if r.item else "") for r in no_serial)
			),
			title=_("Technical close"),
		)


def _label(system_type: str) -> str:
	return frappe.db.get_value("SP List Value", system_type, "value_ar") or system_type


def on_technical_close(doc) -> None:
	"""SP Station on_update, once Technically closed: the warranties and the final invoice."""
	set_warranties(doc)
	final_invoice(doc)


def _quote_years(doc) -> dict:
	if not doc.quotation_accepted:
		return {}
	rows = frappe.get_all(
		"Quotation Item", {"parent": doc.quotation_accepted}, ["item_code", "sp_warranty_years"]
	)
	return {r.item_code: flt(r.sp_warranty_years) for r in rows if flt(r.sp_warranty_years)}


def set_warranties(doc) -> None:
	"""Each component's warranty: from the operation date, the approved quote's years."""
	from smart_power.sp_site.commissioning import warranty_end

	years = _quote_years(doc)
	made = [c.name for c in _commissionings(doc.name)]
	for row in frappe.get_all(
		"SP Station Component",
		{"parent": ("in", made or [""]), "parenttype": COMMISSIONING},
		["name", "item", "warranty_months"],
	):
		months = cint(years.get(row.item, 0) * MONTHS_PER_YEAR) or cint(row.warranty_months)
		frappe.db.set_value(
			"SP Station Component",
			row.name,
			{
				"warranty_months": months,
				"warranty_end": warranty_end(doc.operation_date, months) if months else None,
			},
			update_modified=False,
		)


def final_invoice(doc) -> str | None:
	"""The internal Sales Invoice of the contract, once; the payments are its advances."""
	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

	from smart_power.sp_finance.centers import station_center

	if doc.final_invoice and frappe.db.get_value(SI, doc.final_invoice, "docstatus") == 1:
		return doc.final_invoice
	if not doc.sales_order or frappe.db.get_value(SO, doc.sales_order, "docstatus") != 1:
		frappe.throw(
			_("Station {0} has no signed contract to invoice.").format(doc.name), title=_("Technical close")
		)
	ensure_invoice_series()
	from smart_power.sp_stock.transfers import _as_system

	revenue = frappe.db.get_value(
		"Account", {"company": doc.company, "account_name": REVENUE_ACCOUNT, "is_group": 0}
	)
	center = station_center(doc.company)

	def build_and_post():
		si = make_sales_invoice(doc.sales_order, ignore_permissions=True)
		si.naming_series = INVOICE_SERIES
		si.set_posting_time = 1
		si.posting_date = doc.tech_closed_on or today()
		si.due_date = si.posting_date
		si.project = doc.project
		si.cost_center = center or si.cost_center
		for row in si.items:
			row.project = doc.project
			row.cost_center = si.cost_center
			if revenue:
				row.income_account = revenue
		si.remarks = _("Final invoice of station {0}").format(doc.name)
		_station_advances(si, doc.project)
		si.flags.ignore_permissions = True
		si.insert()
		si.submit()
		return si

	# ERPNext checks the accounts against the session user; the workflow already checked who
	# may close the station (the projects manager or the admin)
	frappe.flags.sp_system_posting = True  # the posting is the system's (SP-26)
	try:
		si = _as_system(build_and_post)
	finally:
		frappe.flags.sp_system_posting = False
	frappe.db.set_value(STATION, doc.name, "final_invoice", si.name, update_modified=False)
	doc.final_invoice = si.name
	return si.name


def _station_advances(si, project: str) -> None:
	"""The payments received on this station are the invoice's advances, oldest first. ERPNext
	would take every advance of the customer, another station's included."""
	si.allocate_advances_automatically = 0
	si.calculate_taxes_and_totals()
	si.set_advances()
	ours = set(
		frappe.get_all(
			"Payment Entry",
			{"name": ("in", [r.reference_name for r in si.advances] or [""]), "project": project},
			pluck="name",
		)
	)
	left = flt(si.rounded_total or si.grand_total)
	rows = []
	for row in si.advances:
		if row.reference_type != "Payment Entry" or row.reference_name not in ours or left <= 0:
			continue
		row.allocated_amount = min(flt(row.advance_amount), left)
		left = flt(left - row.allocated_amount)
		rows.append(row)
	si.set("advances", rows)


def warranty_print(doc) -> frappe._dict:
	"""What the warranty certificate prints: the operation date and each component."""
	from smart_power.sp_core.printing import ar_date, embed_image
	from smart_power.sp_core.services.company import get_company_settings
	from smart_power.sp_stations.station_tabs import warranty

	data = warranty(doc, False)
	for c in data["components"]:
		c.warranty_end_ar = ar_date(c.warranty_end) if c.warranty_end else ""
	stamp = get_company_settings().stamp_image
	return frappe._dict(
		operation_date=ar_date(doc.get("operation_date")) if doc.get("operation_date") else "",
		components=data["components"],
		stamp=embed_image(stamp) if stamp else "",
	)


# --- financial close ------------------------------------------------------------------------------------


def snapshot(doc) -> dict:
	from smart_power.sp_stations.station_tabs import costs

	data = costs(doc, True)
	return {
		"on": str(now_datetime()),
		"agreed": data["agreed"],
		"estimated": data["estimated"],
		"actual": data["actual"],
		"direct": data["direct"],
		"indirect": data["indirect"],
		"lines": data["lines"],
		"expected_profit": data["expected_profit"],
		"actual_profit": data["actual_profit"],
	}


def on_financial_close(doc) -> None:
	"""SP Station on_update, once Financially closed: keep the estimated vs actual cost."""
	if not doc.close_cost_snapshot:
		frappe.db.set_value(
			STATION,
			doc.name,
			"close_cost_snapshot",
			json.dumps(snapshot(doc), default=str),
			update_modified=False,
		)


def settle(station: str) -> bool:
	"""After the money changes: a technically closed station with nothing left closes financially."""
	doc = frappe.get_doc(STATION, station)
	if doc.status != TECH_CLOSED or flt(doc.remaining_amount) > PENNY:
		return False
	# the system's close (a payment's confirmer may not run the workflow), so the status is set
	# directly, as the workflow's Close Financially would
	doc.db_set({"status": FIN_CLOSED, "fin_closed_on": doc.fin_closed_on or today()})
	doc.add_comment("Info", _("Financially closed: nothing remains to collect."))
	doc.reload()
	on_financial_close(doc)
	return True


def on_station_update(doc) -> None:
	if not doc.has_value_changed("status"):
		return
	if doc.status == TECH_CLOSED:
		on_technical_close(doc)
		if flt(doc.remaining_amount) <= PENNY:
			settle(doc.name)  # already paid in full
	elif doc.status == FIN_CLOSED:
		on_financial_close(doc)
