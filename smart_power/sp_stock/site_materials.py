"""Materials on site (SP-90, MR1): what a site asks for, uses and sends back.

    request_materials(...)    the site asks; purchasing turns the request into a transfer order
    record_consumption(...)   a Material Issue from the site warehouse: this is what costs the station
    return_leftovers(...)     unused stock goes site → Transit, and the main store receives it

Stock on site is not yet a station cost, so a return is a plain transfer and never touches the
station's cost. Only what the site still holds can be consumed or returned.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from smart_power.notify import send
from smart_power.sp_core.inbox import close_tasks, create_task
from smart_power.sp_site.site_log import issue_materials
from smart_power.sp_stock.goods_receipt import QTY_DIGITS, _is_serial, my_warehouses
from smart_power.sp_stock.transfers import (
	BUYER,
	CREATORS,
	ENTRY,
	ORDER,
	RECEIVED,
	STATION,
	_as_system,
	_can_create,
	_clean_items,
	_end_transit,
	_holders,
	_is_admin,
	_issued_rows,
	_keepers,
	_left,
	_serials,
	_signed_by_user,
	create_transfer,
)
from smart_power.sp_stock.warehouses import MAIN, TRANSIT, warehouse_of

SITE_REQUEST = "Site Request"
OPEN, CONVERTED = "Open", "Converted"
SENT, RETURNED, DISCREPANCY = "Sent", "Received", "Discrepancy"
CONSUMED, LEFTOVERS = "Consumed", "Leftovers returned"
TASK_REQUEST, TASK_RETURN, TASK_DIFFERENCE = "Material Request", "Return to Receive", "Transfer Difference"
EVENT_REQUEST, EVENT_RETURN, EVENT_DIFFERENCE = (
	"material_requested",
	"return_to_receive",
	"transfer_difference",
)
INSTALLER, PROJECTS = "SP Installation Manager", "SP Project Manager"
CLOSED = ("Financially closed", "Cancelled")


def _station(name: str) -> frappe._dict:
	row = frappe.db.get_value(
		STATION, name, ["name", "project", "company", "site_warehouse", "status"], as_dict=True
	)
	if not row or not row.project or not row.site_warehouse:
		frappe.throw(_("Choose a station that has a site warehouse."))
	if row.status in CLOSED:
		frappe.throw(_("Station {0} is {1}.").format(row.name, _(row.status)))
	return row


def _has_role(*roles: str) -> bool:
	return _is_admin() or bool(set(roles) & set(frappe.get_roles()))


def _check_site(station: frappe._dict) -> None:
	if not _has_role(INSTALLER, PROJECTS) and station.site_warehouse not in my_warehouses():
		frappe.throw(_("You do not work at {0}.").format(station.site_warehouse), frappe.PermissionError)


def _on_hand(warehouse: str, item_code: str) -> float:
	return flt(frappe.db.get_value("Bin", {"warehouse": warehouse, "item_code": item_code}, "actual_qty"))


def _lines(warehouse: str, items: list[dict]) -> list[dict]:
	"""What the site holds, with one serial for each unit of a serial-tracked item."""
	rows = []
	for row in items or []:
		qty, code = flt(row.get("qty"), QTY_DIGITS), row.get("item_code")
		if not code or qty <= 0:
			frappe.throw(_("Enter each item with a quantity above zero."))
		held = _on_hand(warehouse, code)
		if qty > held:
			frappe.throw(
				_("{0}: the site holds {1}.").format(code, held), title=_("More than the site holds")
			)
		rows.append({"item_code": code, "qty": qty, "serial_no": _serials(code, qty, row.get("serial_no"))})
	if not rows:
		frappe.throw(_("Add the items."))
	return rows


# --- requests -------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def request_materials(values: str | dict) -> str:
	"""values: station, items [{item_code, qty}], needed_by, note."""
	values = frappe.parse_json(values)
	station = _station(values.get("station"))
	_check_site(station)
	day = values.get("needed_by") or nowdate()
	doc = frappe.get_doc(
		{
			"doctype": ORDER,
			"material_request_type": "Material Transfer",
			"company": station.company,
			"transaction_date": nowdate(),
			"schedule_date": day,
			"set_warehouse": station.site_warehouse,
			"sp_station": station.name,
			"sp_request_kind": SITE_REQUEST,
			"sp_request_status": OPEN,
			"sp_request_note": values.get("note"),
			"items": [
				{**row, "schedule_date": day, "warehouse": station.site_warehouse, "project": station.project}
				for row in _clean_items(values.get("items"))
			],
		}
	)
	doc.flags.ignore_permissions = True  # checked above
	doc.insert()
	doc.submit()
	users = sorted({*_holders(BUYER), *_holders(PROJECTS)})
	subject = _("Station {0} asks for materials: {1}").format(station.name, doc.name)
	create_task(TASK_REQUEST, ORDER, doc.name, users, subject, description=values.get("note"))
	send(EVENT_REQUEST, users, ORDER, doc.name, subject)
	return doc.name


@frappe.whitelist(methods=["POST"])
def make_transfer(request: str, source_kind: str, transport: str, planned_date: str | None = None) -> str:
	"""Purchasing turns the site's request into a transfer order."""
	if not _can_create():
		frappe.throw(_("Only purchasing creates transfer orders."), frappe.PermissionError)
	if frappe.db.get_value(ORDER, request, "sp_request_status", for_update=True) != OPEN:
		frappe.throw(_("Request {0} is not open.").format(request))
	doc = frappe.get_doc(ORDER, request)
	transfer = create_transfer(
		{
			"station": doc.sp_station,
			"source_kind": source_kind,
			"transport": transport,
			"planned_date": planned_date or doc.schedule_date,
			"items": [{"item_code": r.item_code, "qty": r.qty} for r in doc.items],
		}
	)
	doc.db_set({"sp_request_status": CONVERTED, "sp_transfer_order": transfer})
	close_tasks(ORDER, doc.name, TASK_REQUEST)
	return transfer


# --- consumption ----------------------------------------------------------------------------------


def refresh_transfers(station: str) -> None:
	"""A received transfer whose goods have all left the site is finished."""
	site = frappe.db.get_value(STATION, station, "site_warehouse")
	returned = set(
		frappe.get_all(
			"Stock Entry Detail",
			{"parent": ("in", _returns_of(station) or [""])},
			pluck="item_code",
		)
	)
	for name in frappe.get_all(ORDER, {"sp_station": station, "sp_transfer_status": RECEIVED}, pluck="name"):
		items = set(frappe.get_all("Material Request Item", {"parent": name}, pluck="item_code"))
		if items and not any(_on_hand(site, code) > 0 for code in items):
			frappe.db.set_value(
				ORDER, name, "sp_transfer_status", LEFTOVERS if items & returned else CONSUMED
			)


def _returns_of(station: str) -> list[str]:
	return frappe.get_all(
		ENTRY, {"sp_station": station, "sp_return_status": RETURNED, "docstatus": 1}, pluck="name"
	)


@frappe.whitelist(methods=["POST"])
def record_consumption(values: str | dict) -> str:
	"""values: station, posting_date, items [{item_code, qty, serial_no}]. The installation manager
	enters what was used on site, and its value becomes the station's material cost."""
	if not _has_role(INSTALLER):
		frappe.throw(_("Only the installation manager records site consumption."), frappe.PermissionError)
	values = frappe.parse_json(values)
	station = _station(values.get("station"))
	rows = _lines(station.site_warehouse, values.get("items"))
	day = values.get("posting_date") or nowdate()
	remark = _("Materials used on site: station {0}").format(station.name)
	entry = _as_system(
		lambda: issue_materials(station.company, station.site_warehouse, station.project, rows, day, remark)
	)
	_signed_by_user(entry)
	refresh_transfers(station.name)
	return entry


# --- returns --------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def return_leftovers(values: str | dict) -> str:
	"""values: station, items [{item_code, qty, serial_no}]. The goods leave the site for Transit."""
	values = frappe.parse_json(values)
	station = _station(values.get("station"))
	_check_site(station)
	rows = _lines(station.site_warehouse, values.get("items"))
	transit, main = warehouse_of(station.company, TRANSIT), warehouse_of(station.company, MAIN)
	if not transit or not main:
		frappe.throw(_("Company {0} has no transit warehouse.").format(station.company))
	entry = frappe.get_doc(
		{
			"doctype": ENTRY,
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": station.company,
			"add_to_transit": 1,
			"from_warehouse": station.site_warehouse,
			"to_warehouse": transit,
			"project": station.project,
			"sp_station": station.name,
			"sp_return_status": SENT,
			"remarks": _("Leftovers returned from station {0}").format(station.name),
			"items": [
				{
					"item_code": row["item_code"],
					"qty": row["qty"],
					"s_warehouse": station.site_warehouse,
					"t_warehouse": transit,
					"project": station.project,
					"use_serial_batch_fields": 1 if row["serial_no"] else 0,
					"serial_no": row["serial_no"],
				}
				for row in rows
			],
		}
	)
	entry.flags.ignore_permissions = True

	def post():
		entry.insert()
		entry.submit()

	_as_system(post)
	_signed_by_user(entry.name)
	users = _keepers(main, MAIN)
	subject = _("Receive the return {0} from station {1}").format(entry.name, station.name)
	create_task(TASK_RETURN, ENTRY, entry.name, users, subject)
	send(EVENT_RETURN, users, ENTRY, entry.name, subject)
	return entry.name


@frappe.whitelist(methods=["POST"])
def receive_return(name: str, lines: str | list) -> dict:
	"""The main store counts the return. lines: [{row: the return entry's row, qty}]."""
	if frappe.db.get_value(ENTRY, name, "sp_return_status", for_update=True) not in (SENT, DISCREPANCY):
		frappe.throw(_("Return {0} is not waiting to be received.").format(name))
	doc = frappe.get_doc(ENTRY, name)
	main = warehouse_of(doc.company, MAIN)
	if not _is_admin() and main not in my_warehouses():
		frappe.throw(_("You do not work at {0}.").format(main), frappe.PermissionError)
	lines = frappe.parse_json(lines) if isinstance(lines, str) else lines
	rows = {r.name: r for r in _issued_rows(name)}
	confirmed: dict[str, float] = {}
	for line in lines or []:
		row, qty = rows.get(line.get("row")), flt(line.get("qty"), QTY_DIGITS)
		if not row:
			frappe.throw(_("A line does not belong to return {0}.").format(name))
		if qty < 0 or qty > _left(row):
			frappe.throw(_("{0}: only {1} are still in transit.").format(row.item_code, _left(row)))
		if _is_serial(row.item_code) and qty not in (0, _left(row)):
			frappe.throw(_("{0}: confirm all its serial numbers or none.").format(row.item_code))
		confirmed[row.name] = qty
	if not any(confirmed.values()):
		frappe.throw(_("Enter what arrived."))
	entry = _as_system(lambda: _end_transit(name, confirmed, doc.project, main))
	_signed_by_user(entry)
	close_tasks(ENTRY, name, TASK_RETURN)
	short = sum(_left(r) for r in _issued_rows(name))
	if short > 0:
		doc.db_set("sp_return_status", DISCREPANCY)
		users = sorted({*_holders(BUYER), *_holders(PROJECTS)})
		subject = _("Return {0}: {1} still in transit after the store's count").format(name, flt(short))
		create_task(TASK_DIFFERENCE, ENTRY, name, users, subject)
		send(EVENT_DIFFERENCE, users, ENTRY, name, subject)
		return {"entry": entry, "status": DISCREPANCY, "short": flt(short)}
	doc.db_set("sp_return_status", RETURNED)
	close_tasks(ENTRY, name, TASK_DIFFERENCE)
	refresh_transfers(doc.sp_station)
	return {"entry": entry, "status": RETURNED, "short": 0}


# --- the screens ---------------------------------------------------------------------------------


@frappe.whitelist()
def site_overview(station: str) -> dict:
	"""What the site holds, what it asked for and what it sent back. Quantities only."""
	row = _station(station)
	_check_site(row)
	stock = frappe.get_all(
		"Bin",
		{"warehouse": row.site_warehouse, "actual_qty": (">", 0)},
		["item_code", "actual_qty", "stock_uom"],
		order_by="item_code asc",
	)
	for line in stock:
		item = frappe.get_cached_value("Item", line.item_code, ["item_name", "has_serial_no"], as_dict=True)
		line.update({"item_name": item.item_name, "serial": bool(item.has_serial_no)})
	return {
		"station": row.name,
		"site": row.site_warehouse,
		"stock": stock,
		"can_consume": _has_role(INSTALLER),
		"requests": frappe.get_all(
			ORDER,
			{"sp_station": station, "sp_request_kind": SITE_REQUEST},
			["name", "sp_request_status as status", "schedule_date", "sp_transfer_order as transfer"],
			order_by="creation desc",
			limit=20,  # sp-allow-number: a screenful
		),
		"returns": frappe.get_all(
			ENTRY,
			{"sp_station": station, "sp_return_status": ("is", "set")},
			["name", "sp_return_status as status", "posting_date"],
			order_by="creation desc",
			limit=20,  # sp-allow-number: a screenful
		),
	}


@frappe.whitelist()
def my_sites() -> list[dict]:
	"""The stations this user works on site."""
	filters = {"status": ("not in", CLOSED), "site_warehouse": ("is", "set")}
	if not _has_role(INSTALLER, PROJECTS):
		filters["site_warehouse"] = ("in", my_warehouses() or [""])
	return frappe.get_all(STATION, filters, ["name", "customer_name"], order_by="creation desc")


@frappe.whitelist()
def open_requests() -> list[dict]:
	if not _can_create():
		return []
	rows = frappe.get_all(
		ORDER,
		{"sp_request_kind": SITE_REQUEST, "sp_request_status": OPEN},
		["name", "sp_station as station", "schedule_date", "sp_request_note as note", "owner"],
		order_by="creation asc",
	)
	for row in rows:
		row.lines = frappe.get_all(
			"Material Request Item",
			{"parent": row.name},
			["item_code", "item_name", "qty", "uom"],
			order_by="idx asc",
		)
	return rows


@frappe.whitelist()
def returns_to_receive() -> list[dict]:
	"""What is on its way back to the main store I work at."""
	rows = frappe.get_all(
		ENTRY,
		{"sp_return_status": ("in", (SENT, DISCREPANCY)), "docstatus": 1},
		["name", "sp_station as station", "sp_return_status as status", "company", "posting_date"],
		order_by="creation asc",
	)
	mine, cards = set(my_warehouses()), []
	for row in rows:
		if not _is_admin() and warehouse_of(row.company, MAIN) not in mine:
			continue
		row.lines = [
			{
				"row": r.name,
				"item_code": r.item_code,
				"item_name": r.item_name,
				"uom": r.uom,
				"left": _left(r),
				"serial": _is_serial(r.item_code),
			}
			for r in _issued_rows(row.name)
			if _left(r) > 0
		]
		cards.append(row)
	return cards


def return_print(doc) -> frappe._dict:
	"""What the return note prints: quantities and serials, never a price."""
	from smart_power.sp_core.printing import ar_date

	return frappe._dict(
		no=doc.name,
		date=ar_date(doc.posting_date),
		station=doc.get("sp_station"),
		source=doc.from_warehouse or (doc.items[0].s_warehouse if doc.items else ""),
		target=warehouse_of(doc.company, MAIN),
		lines=[
			{
				"no": row.idx,
				"item_code": row.item_code,
				"description": row.item_name,
				"uom": row.uom,
				"qty": flt(row.qty),
				"serial_no": row.serial_no,
			}
			for row in doc.items
		],
	)
