"""S2 Station record (SP-76): one record with a tab for every part of the job.

    tabs(station)         the tabs this user sees, and whether they see amounts
    tab(station, name)    one tab's content; a tab the user may not see is refused (403)

Which tabs a role sees is the admin's table in Smart Power Settings (Station Tabs by Role, the
X2 field rules; seeded by seed_tab_access). A user sees the tabs of all their roles. On top of it:

- the Costs tab also needs a cost role (permissions.can_see_cost), and the seed gives it to the
  admin only (owner, 2026-11-20);
- amounts follow the station's own role permissions: its money fields are on permlevel 1, and
  the site roles (مصطفى) have no permlevel 1, so no tab sends them an amount;
- supplier prices on the purchase orders are for the purchase officer and the admin only.

Tabs and their sources:

    overview      key dates, timeline, open tasks, alerts
    scope         the systems, the accepted quote's quantities, change orders, site returns
    agreement     the contract (Sales Order): lines, discount, payment terms, its PDF
    payments      schedule with status, customer payments, cheques, the Agri Bank advance
    purchasing    purchase orders, receipts, consignment withdrawals, transfers, stock entries
    site          tasks, site daily logs and labour, winch and car jobs, site expenses
    programming   the commissioning per system: inverter, settings file, readings
    documents     the files on the station; quote versions, contract and invoices
    warranty      component warranties from the operation date
    costs         estimated (frozen) against actual cost (costing.actual_cost), profit
    history       ownership history and every field change
"""

import json
from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.utils import cint, flt, get_fullname, getdate, today

from smart_power.permissions import can_see_cost

CONTRACT_PRINT = "SP Contract"


def contract_pdf_url(sales_order: str) -> str:
	"""The contract's PDF, encoded once here: the page uses the link as it is (BUG-9)."""
	query = urlencode({"doctype": "Sales Order", "name": sales_order, "format": CONTRACT_PRINT})
	return f"/api/method/frappe.utils.print_format.download_pdf?{query}"


STATION = "SP Station"
SETTINGS = "Smart Power Settings"
ACCESS_TABLE = "station_tab_access"
TABS = (
	"overview",
	"scope",
	"agreement",
	"payments",
	"purchasing",
	"site",
	"programming",
	"documents",
	"warranty",
	"costs",
	"history",
)
COSTS = "costs"
ALL_TABS_ROLES = ("System Manager",)
SUPPLIER_PRICE_ROLES = ("SP Admin", "System Manager", "SP Purchase Officer")
NOT_CANCELLED = ("<", 2)  # sp-allow-number: docstatus 2 is cancelled
SUBMITTED = 1  # sp-allow-number: docstatus
RECENT = 100  # sp-allow-number: the latest field changes shown in History


# ---------------------------------------------------------------- who sees which tab


def seed_tab_access(force: bool = False) -> None:
	"""The seed's role → tab map, where the admin has not set one."""
	from smart_power.sp_core.setup.seed import defaults

	settings = frappe.get_single(SETTINGS)
	if settings.get(ACCESS_TABLE) and not force:
		return
	seed = defaults()["station_tab_access"]
	settings.set(ACCESS_TABLE, [])
	for role, profile in seed["roles"].items():
		if frappe.db.exists("Role", role):
			settings.append(ACCESS_TABLE, {"role": role, **{f"tab_{t}": 1 for t in seed[profile]}})
	settings.flags.ignore_permissions = True
	settings.save()


def tabs_for(user: str | None = None) -> list[str]:
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or roles & set(ALL_TABS_ROLES):
		return list(TABS)
	rows = [r for r in frappe.get_cached_doc(SETTINGS).get(ACCESS_TABLE) or [] if r.role in roles]
	allowed = [t for t in TABS if any(cint(r.get(f"tab_{t}")) for r in rows)]
	if COSTS in allowed and not can_see_cost(user):
		allowed.remove(COSTS)
	return allowed


def sees_amounts(doc) -> bool:
	"""The station's money fields are on permlevel 1: whoever reads them sees amounts."""
	return doc.has_permlevel_access_to("agreed_amount")


def _sees_supplier_prices() -> bool:
	return frappe.session.user == "Administrator" or bool(set(SUPPLIER_PRICE_ROLES) & set(frappe.get_roles()))


def _station(station: str):
	doc = frappe.get_doc(STATION, station)
	doc.check_permission("read")
	return doc


@frappe.whitelist()
def tabs(station: str) -> dict:
	doc = _station(station)
	return {"tabs": tabs_for(), "amounts": sees_amounts(doc)}


@frappe.whitelist()
def tab(station: str, name: str) -> dict:
	if name not in TABS:
		frappe.throw(_("Unknown station tab {0}.").format(frappe.bold(name)))
	doc = _station(station)
	if name not in tabs_for():
		frappe.throw(_("You cannot see this tab of the station."), frappe.PermissionError)
	amounts = sees_amounts(doc)
	return BUILDERS[name](doc, amounts)


# ---------------------------------------------------------------- helpers


def _labels(names) -> dict:
	names = [n for n in set(names) if n]
	if not names:
		return {}
	return dict(frappe.get_all("SP List Value", {"name": ("in", names)}, ["name", "value_ar"], as_list=True))


def _name(user: str | None) -> str:
	return get_fullname(user) if user else ""


def _money(rows: list, amounts: bool, *keys: str) -> list:
	"""Without amounts, the money keys are removed from every row."""
	if amounts:
		return rows
	for row in rows:
		for key in keys:
			row.pop(key, None)
	return rows


def _open_tasks(doc) -> list:
	refs = [(STATION, doc.name)]
	if doc.sales_order:
		refs.append(("Sales Order", doc.sales_order))
	tasks = []
	for doctype, name in refs:
		tasks += frappe.get_all(
			"SP Task",
			{"reference_doctype": doctype, "reference_name": name, "status": "Open"},
			["name", "subject", "task_type", "assigned_to", "due_at"],
			order_by="due_at asc",
		)
	for t in tasks:
		t.assigned_to_name = _name(t.assigned_to)
	return tasks


def _orders(doc) -> list:
	return frappe.get_all(
		"Purchase Order",
		{"sp_station": doc.name, "docstatus": NOT_CANCELLED},
		[
			"name",
			"supplier_name",
			"transaction_date",
			"sp_status",
			"sp_next_delivery",
			"sp_destination_type",
			"grand_total",
			"currency",
		],
		order_by="transaction_date asc, name asc",
	)


def _transfers(doc) -> list:
	return frappe.get_all(
		"Material Request",
		{"sp_station": doc.name, "docstatus": NOT_CANCELLED, "sp_transfer_status": ("is", "set")},
		["name", "transaction_date", "sp_transfer_status", "sp_source_kind", "sp_transport"],
		order_by="transaction_date asc, name asc",
	)


def _first(doctype: str, filters: dict, field: str):
	rows = frappe.get_all(doctype, filters, [field], order_by=f"{field} asc", limit=1, pluck=field)
	return rows[0] if rows else None


# ---------------------------------------------------------------- the tabs


def overview(doc, amounts: bool) -> dict:
	orders = _orders(doc)
	order_names = [o.name for o in orders] or [""]
	waiting = [o for o in orders if o.sp_status not in ("Received", "Closed", "Cancelled")]
	next_delivery = min((o.sp_next_delivery for o in waiting if o.sp_next_delivery), default=None)
	events = [
		(doc.creation, _("Station opened")),
		(doc.contract_date, _("Contract signed")),
		(
			# when the customer paid is money: not for the site view
			_first(
				"Payment Entry",
				{"project": doc.project or "", "docstatus": SUBMITTED, "payment_type": "Receive"},
				"posting_date",
			)
			if amounts
			else None,
			_("First payment confirmed"),
		),
		(orders[0].transaction_date if orders else None, _("First purchase order")),
		(
			_first(
				"Purchase Receipt",
				{"sp_purchase_order": ("in", order_names), "docstatus": NOT_CANCELLED},
				"posting_date",
			),
			_("First goods received"),
		),
		(
			_first(
				"Material Request",
				{"sp_station": doc.name, "sp_transfer_status": ("in", ("Issued", "Received"))},
				"transaction_date",
			),
			_("First transfer to the site"),
		),
		(
			_first("SP Site Daily Log", {"station": doc.name, "docstatus": SUBMITTED}, "work_date"),
			_("Installation started on site"),
		),
		(doc.operation_date, _("In operation")),
		(doc.tech_closed_on, _("Technically closed")),
		(doc.fin_closed_on, _("Financially closed")),
	]
	timeline = sorted(
		({"date": str(getdate(when)), "label": label} for when, label in events if when),
		key=lambda e: e["date"],
	)
	alerts = []
	if amounts and doc.has_overdue:
		alerts.append(
			_("Overdue: {0} from the customer").format(frappe.format(doc.overdue_amount, "Currency"))
		)
	if amounts and flt(doc.pending_amount):
		alerts.append(
			_("{0} in payments waiting for the admin's confirmation").format(
				frappe.format(doc.pending_amount, "Currency")
			)
		)
	late = [o.name for o in waiting if o.sp_next_delivery and getdate(o.sp_next_delivery) < getdate(today())]
	if late:
		alerts.append(_("Delivery late on {0}").format(", ".join(late)))
	short = [t.name for t in _transfers(doc) if t.sp_transfer_status == "Discrepancy"]
	if short:
		alerts.append(_("Less arrived than left on {0}").format(", ".join(short)))
	return {
		"dates": {
			"contract_date": doc.contract_date,
			"next_delivery": next_delivery,
			"operation_date": doc.operation_date,
			"tech_closed_on": doc.tech_closed_on,
			"fin_closed_on": doc.fin_closed_on,
		},
		"timeline": timeline,
		"tasks": _open_tasks(doc),
		"alerts": alerts,
	}


def scope(doc, amounts: bool) -> dict:
	labels = _labels(r.system_type for r in doc.systems)
	systems = [
		{
			"system_type": labels.get(r.system_type) or r.system_type,
			"capacity_kw": r.capacity_kw,
			"hp": r.hp,
			"qty": r.qty,
			"notes": r.notes,
		}
		for r in doc.systems
	]
	lines = []
	if doc.quotation_accepted:
		lines = frappe.get_all(
			"Quotation Item",
			{"parent": doc.quotation_accepted, "parenttype": "Quotation"},
			["item_code", "item_name", "qty", "uom"],
			order_by="idx asc",
		)
	returns = frappe.get_all(
		"Stock Entry",
		{"sp_station": doc.name, "docstatus": SUBMITTED, "sp_return_status": ("is", "set")},
		["name", "posting_date", "sp_return_status"],
		order_by="posting_date asc",
	)
	from smart_power.sp_stations.change_order import of_station

	return {
		"systems": systems,
		"capacity_kw_total": doc.capacity_kw_total,
		"quote": doc.quotation_accepted,
		"lines": lines,
		"returns": returns,
		# the scope changes after signing (SP-78); amounts only for those who see them
		"change_orders": _money(of_station(doc.name), amounts, "delta_amount"),
	}


def agreement(doc, amounts: bool) -> dict:
	if not doc.sales_order:
		return {"contract": None}
	so = frappe.get_doc("Sales Order", doc.sales_order)
	return {
		"contract": so.name,
		"date": so.transaction_date,
		"signed": so.docstatus == SUBMITTED,
		"pdf": contract_pdf_url(so.name),
		"lines": _money(
			[
				{
					"item_code": r.item_code,
					"item_name": r.item_name,
					"qty": r.qty,
					"rate": r.rate,
					"amount": r.amount,
				}
				for r in so.items
			],
			amounts,
			"rate",
			"amount",
		),
		"discount_pct": so.additional_discount_percentage if amounts else None,
		"discount_amount": so.discount_amount if amounts else None,
		"total": (so.rounded_total or so.grand_total) if amounts else None,
		"terms": _money(
			[
				{"due_date": r.due_date, "description": r.description, "amount": r.payment_amount}
				for r in so.payment_schedule
			],
			amounts,
			"amount",
		),
		"financing": _labels([doc.financing_type]).get(doc.financing_type) or doc.financing_type,
		"bank_branch": doc.bank_branch,
	}


def schedule_status(schedule: list, covered: float) -> list:
	"""Each instalment's status against the paid and written-off money, oldest first."""
	rows, left = [], flt(covered)
	for due_date, amount in schedule:
		paid = min(flt(amount), max(left, 0.0))
		left -= paid
		if paid >= flt(amount) - 0.005:  # sp-allow-number: half a piastre, rounding
			status = "Paid"
		elif getdate(due_date) < getdate(today()):
			status = "Overdue"
		elif paid:
			status = "Partly paid"
		else:
			status = "Due"
		rows.append({"due_date": str(due_date), "amount": amount, "paid": paid, "status": status})
	return rows


def payments(doc, amounts: bool) -> dict:
	from smart_power.sp_stations.money import _agreed_and_schedule

	_agreed, schedule = _agreed_and_schedule(doc)
	covered = flt(doc.paid_amount) + flt(doc.write_off_amount)
	received = frappe.get_all(
		"SP Customer Payment",
		{"station": doc.name, "docstatus": NOT_CANCELLED},
		[
			"name",
			"work_date",
			"amount",
			"method",
			"channel",
			"status",
			"is_deposit",
			"recorded_by",
			"third_party_type",
			"third_party",
		],
		order_by="work_date asc, creation asc",
	)
	labels = _labels(r.method for r in received)
	for r in received:
		r.method = labels.get(r.method) or r.method
		r.recorded_by_name = _name(r.recorded_by)
	cheques = frappe.get_all(
		"SP Cheque",
		{"station": doc.name},
		["name", "cheque_no", "amount", "due_date", "status", "holder", "holder_name", "bank_or_post"],
		order_by="due_date asc",
	)
	advances = frappe.get_all(
		"SP Customer Advance",
		{"station": doc.name, "docstatus": NOT_CANCELLED},
		["name", "status", "bank", "amount", "repaid_amount", "outstanding_amount", "paid_on"],
	)
	result = {
		"summary": {
			"agreed": doc.agreed_amount,
			"paid": doc.paid_amount,
			"pending": doc.pending_amount,
			"written_off": doc.write_off_amount,
			"remaining": doc.remaining_amount,
		},
		"schedule": schedule_status(schedule, covered),
		"payments": [r for r in received if not r.third_party],
		# paid by the customer straight to a third party (a supplier, a worker) on the station
		"third_party": [r for r in received if r.third_party],
		"cheques": cheques,
		"advances": advances,
	}
	if not amounts:
		result.pop("summary")
		for key in ("schedule", "payments", "third_party", "cheques", "advances"):
			_money(result[key], False, "amount", "paid", "repaid_amount", "outstanding_amount")
	return result


def purchasing(doc, amounts: bool) -> dict:
	orders = _orders(doc)
	prices = amounts and _sees_supplier_prices()
	if not prices:
		for o in orders:
			o.pop("grand_total", None)
	receipts = frappe.get_all(
		"Purchase Receipt",
		{"sp_purchase_order": ("in", [o.name for o in orders] or [""]), "docstatus": NOT_CANCELLED},
		["name", "posting_date", "sp_purchase_order", "sp_receipt_status", "set_warehouse"],
		order_by="posting_date asc",
	)
	consignment = frappe.get_all(
		"SP Consignment Movement",
		{"station": doc.name, "docstatus": NOT_CANCELLED},
		["name", "movement_type", "movement_date", "item", "qty", "status", "purchase_order"],
		order_by="movement_date asc",
	)
	entries = frappe.get_all(
		"Stock Entry",
		{"sp_station": doc.name, "docstatus": SUBMITTED},
		["name", "posting_date", "stock_entry_type", "purpose", "sp_return_status"],
		order_by="posting_date asc, name asc",
	)
	return {
		"orders": orders,
		"supplier_prices": prices,
		"receipts": receipts,
		"consignment": consignment,
		"transfers": _transfers(doc),
		"stock_entries": entries,
	}


def site(doc, amounts: bool) -> dict:
	tasks = frappe.get_all(
		"SP Task",
		{"reference_doctype": STATION, "reference_name": doc.name},
		["name", "subject", "status", "assigned_to", "due_at"],
		order_by="status asc, due_at asc",
	)
	for t in tasks:
		t.assigned_to_name = _name(t.assigned_to)
	logs = frappe.get_all(
		"SP Site Daily Log",
		{"station": doc.name, "docstatus": NOT_CANCELLED},
		["name", "work_date", "docstatus", "labour_total", "issues", "owner"],
		order_by="work_date desc",
	)
	for log in logs:
		log.crew = frappe.db.count("SP Crew Line", {"parent": log.name, "parenttype": "SP Site Daily Log"})
		log.logged_by = _name(log.owner)
		log.pop("owner")
	jobs = frappe.get_all(
		"SP Field Entry",
		{"station": doc.name, "entry_kind": "Job"},
		["name", "work_date", "vehicle", "job_type", "hours", "days", "agreed_amount", "status"],
		order_by="work_date desc",
	)
	bookings = frappe.get_all(
		"SP Vehicle Booking",
		{"station": doc.name, "status": ("in", ("Expected", "Booked"))},
		["name", "planned_date", "vehicle", "job_type", "status", "agreed_amount"],
		order_by="planned_date asc",
	)
	labels = _labels([*(j.job_type for j in jobs), *(b.job_type for b in bookings)])
	for row in (*jobs, *bookings):
		row.job_type = labels.get(row.job_type) or row.job_type
	expenses = frappe.get_all(
		"SP Custody Line",
		{"station": doc.name, "status": ("!=", "Rejected")},
		["name", "parent", "work_date", "expense_type", "amount", "status", "note"],
		order_by="work_date desc",
	)
	expense_labels = _labels(e.expense_type for e in expenses)
	for e in expenses:
		e.expense_type = expense_labels.get(e.expense_type) or e.expense_type
	from smart_power.sp_site.site_tasks import board

	return {
		"tasks": tasks,
		"site_tasks": board(doc.name),  # S2 (SP-100)
		"logs": _money(logs, amounts, "labour_total"),
		"labour_total": sum(flt(log.get("labour_total")) for log in logs if log.docstatus == SUBMITTED)
		if amounts
		else None,
		"jobs": _money(jobs, amounts, "agreed_amount"),
		"bookings": _money(bookings, amounts, "agreed_amount"),
		"expenses": _money(expenses, amounts, "amount"),
		"site_receiver": _name(doc.site_receiver),
	}


def programming(doc, amounts: bool) -> dict:
	rows = frappe.get_all(
		"SP Commissioning",
		{"station": doc.name, "docstatus": NOT_CANCELLED},
		[
			"name",
			"docstatus",
			"system_type",
			"inverter_brand",
			"inverter_model",
			"inverter_serial",
			"settings_file",
			"remote_support_id",
			"operation_date",
		],
		order_by="creation asc",
	)
	labels = _labels([*(r.system_type for r in rows), *(r.inverter_brand for r in rows)])
	for r in rows:
		r.system_type = labels.get(r.system_type) or r.system_type
		r.inverter_brand = labels.get(r.inverter_brand) or r.inverter_brand
		r.settings = (
			frappe.db.get_value(
				"SP Settings File", r.settings_file, ["title", "version", "file"], as_dict=True
			)
			if r.settings_file
			else None
		)
		r.readings = frappe.get_all(
			"SP Commissioning Reading",
			{"parent": r.name, "parenttype": "SP Commissioning"},
			["param", "value", "unit"],
			order_by="idx asc",
		)
	return {"commissionings": rows, "operation_date": doc.operation_date}


def documents(doc, amounts: bool) -> dict:
	files = frappe.get_all(
		"File",
		{"attached_to_doctype": STATION, "attached_to_name": doc.name, "is_folder": 0},
		["name", "file_name", "file_url", "creation", "owner"],
		order_by="creation desc",
	)
	for f in files:
		f.uploaded_by = _name(f.pop("owner"))
	result = {"files": files, "quotes": [], "contract": None, "invoices": []}
	if not amounts:  # the priced documents are for those who see amounts
		return result
	if doc.case:
		result["quotes"] = frappe.get_all(
			"Quotation",
			{"sp_case": doc.case, "docstatus": NOT_CANCELLED},
			["name", "sp_version", "sp_option_label", "sp_status", "transaction_date", "grand_total"],
			order_by="creation asc",
		)
	if doc.sales_order:
		result["contract"] = {
			"name": doc.sales_order,
			"pdf": contract_pdf_url(doc.sales_order),
		}
	if doc.project:
		result["invoices"] = frappe.get_all(
			"Sales Invoice",
			{"project": doc.project, "docstatus": SUBMITTED},
			["name", "posting_date", "grand_total", "status"],
			order_by="posting_date asc",
		)
	return result


def warranty(doc, amounts: bool) -> dict:
	made = frappe.get_all("SP Commissioning", {"station": doc.name, "docstatus": SUBMITTED}, pluck="name")
	components = frappe.get_all(
		"SP Station Component",
		{"parent": ("in", made or [""]), "parenttype": "SP Commissioning"},
		["component_type", "item", "serial", "warranty_months", "warranty_end"],
		order_by="idx asc",
	)
	names = dict(
		frappe.get_all(
			"Item",
			{"name": ("in", [c.item for c in components if c.item] or [""])},
			["name", "item_name"],
			as_list=True,
		)
	)
	for c in components:
		c.item_name = names.get(c.item) or c.item
		c.active = bool(c.warranty_end) and getdate(c.warranty_end) >= getdate(today())
	return {"operation_date": doc.operation_date, "components": components}


def costs(doc, amounts: bool) -> dict:
	from smart_power.sp_stations.costing import actual_cost

	snapshot = json.loads(doc.estimated_cost_snapshot or "{}")
	estimated = flt(snapshot.get("total_cost"))
	actual = actual_cost(doc.name)
	agreed = flt(doc.agreed_amount)
	return {
		"agreed": agreed,
		"estimated": estimated,
		"frozen_on": snapshot.get("frozen_on"),
		"actual": actual["total"],
		"direct": actual["direct"],
		"indirect": actual["indirect"],
		"lines": actual["lines"],
		"expected_profit": agreed - estimated,
		"actual_profit": agreed - actual["total"],
	}


def history(doc, amounts: bool) -> dict:
	owners = [
		{
			"role_kind": r.role_kind,
			"from_user": _name(r.from_user),
			"to_user": _name(r.to_user),
			"from_date": r.from_date,
			"reason": r.reason,
			"changed_by": _name(r.changed_by),
		}
		for r in doc.owner_history
	]
	meta = doc.meta
	changes = []
	for v in frappe.get_all(
		"Version",
		{"ref_doctype": STATION, "docname": doc.name},
		["owner", "creation", "data"],
		order_by="creation desc",
		limit=RECENT,
	):
		data = json.loads(v.data or "{}")
		for fieldname, old, new in data.get("changed") or []:
			df = meta.get_field(fieldname)
			if not df or not doc.has_permlevel_access_to(fieldname, df=df):
				continue  # an amount or a cost this user does not see
			if not old and not new:
				continue  # empty to zero when the station was first saved: nothing changed
			changes.append(
				{
					"when": v.creation,
					"by": _name(v.owner),
					"field": _(df.label),
					"old": old,
					"new": new,
				}
			)
	return {"owners": owners, "changes": changes}


BUILDERS = {
	"overview": overview,
	"scope": scope,
	"agreement": agreement,
	"payments": payments,
	"purchasing": purchasing,
	"site": site,
	"programming": programming,
	"documents": documents,
	"warranty": warranty,
	"costs": costs,
	"history": history,
}
