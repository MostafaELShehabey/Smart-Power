"""Transfer orders (SP-88, I4): stock leaves a store for a station's site and is tracked until the
site confirms it.

    Created (a Material Request) → Issued (source → Transit) → Received, or Discrepancy when less
    arrived than left

Purchasing creates the order and the store or showroom issues it with a transfer note. The goods
stay in the Transit warehouse until the site receiver confirms what arrived (End Transit). What is
short stays in Transit, and purchasing gets a task. Showroom stock moves at cost, because a transfer
carries its valuation. Every entry carries the station's Project, and no price reaches these screens.

The showroom refills itself the same way (SP-89): request_refill asks the main store for items, the
main store keeper issues them into Transit, and the showroom store keeper confirms what arrived. A
refill has no station and no project: it is an internal move at cost, so it books no showroom income.
"""

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry import make_stock_in_entry
from frappe import _
from frappe.utils import cstr, flt, get_fullname, nowdate

from smart_power.notify import send
from smart_power.sp_core.inbox import close_tasks, create_task
from smart_power.sp_stock.goods_receipt import QTY_DIGITS, SITE_ROLE, STORE_ROLES, _is_serial, my_warehouses
from smart_power.sp_stock.warehouses import MAIN, SHOWROOM, TRANSIT, site_warehouse, warehouse_of

ORDER, ENTRY, ENTRY_ROW, STATION = "Material Request", "Stock Entry", "Stock Entry Detail", "SP Station"
CREATED, ISSUED, RECEIVED, DISCREPANCY, CANCELLED = (
	"Created",
	"Issued",
	"Received",
	"Discrepancy",
	"Cancelled",
)
JUMBO, WINCH, OTHER = "Jumbo", "Winch", "Other"
TRANSPORTS = (JUMBO, WINCH, OTHER)
SOURCES = (MAIN, SHOWROOM)
TASK_ISSUE, TASK_RECEIVE, TASK_DIFFERENCE = "Transfer to Issue", "Transfer to Receive", "Transfer Difference"
EVENT_ISSUE, EVENT_RECEIVE, EVENT_DIFFERENCE = (
	"transfer_to_issue",
	"transfer_to_receive",
	"transfer_difference",
)
BUYER = "SP Purchase Officer"
REFILLERS = ("SP Showroom Store Keeper", "SP Showroom Sales", "SP Admin", "System Manager")
ADMIN_ROLES = ("SP Admin", "System Manager")
CREATORS = (BUYER, "SP Project Manager", *ADMIN_ROLES)
RECENT = 50  # sp-allow-number: a screenful of the latest transfers


def _is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def _can_create() -> bool:
	return frappe.session.user == "Administrator" or bool(set(CREATORS) & set(frappe.get_roles()))


def _holders(role: str) -> list[str]:
	users = frappe.get_all("Has Role", {"role": role, "parenttype": "User"}, pluck="parent")
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")


def _keepers(warehouse: str, kind: str) -> list[str]:
	"""Who issues from this store: its responsible user, else the holders of its role."""
	responsible = frappe.db.get_value("Warehouse", warehouse, "sp_responsible_user")
	return [responsible] if responsible else _holders(STORE_ROLES[kind])


def _receivers(station: str) -> list[str]:
	"""Who confirms at this site: the station's receiver, else the site receivers."""
	receiver = frappe.db.get_value(STATION, station, "site_receiver")
	return [receiver] if receiver else _holders(SITE_ROLE)


def _as_system(action):
	"""ERPNext checks accounts against the session user, and a store keeper may not read them.
	The caller has already checked who may do this."""
	user = frappe.session.user
	frappe.set_user("Administrator")  # nosemgrep
	try:
		return action()
	finally:
		frappe.set_user(user)  # nosemgrep


def _signed_by_user(entry: str) -> None:
	"""The entry shows who issued or confirmed it, not the system that posted it."""
	user = frappe.session.user
	frappe.db.set_value(ENTRY, entry, {"owner": user, "modified_by": user}, update_modified=False)


def _clean_items(items: list[dict]) -> list[dict]:
	totals: dict[str, float] = {}
	for row in items or []:
		qty = flt(row.get("qty"), QTY_DIGITS)
		if not row.get("item_code") or qty <= 0:
			frappe.throw(_("Enter each item with a quantity above zero."))
		if not frappe.db.get_value("Item", row["item_code"], "is_stock_item"):
			frappe.throw(_("{0} is not a stock item.").format(row["item_code"]))
		totals[row["item_code"]] = totals.get(row["item_code"], 0) + qty
	if not totals:
		frappe.throw(_("Add the items to transfer."))
	return [{"item_code": code, "qty": qty} for code, qty in totals.items()]


@frappe.whitelist(methods=["POST"])
def create_transfer(values: str | dict) -> str:
	"""values: station, source_kind (Main / Showroom), transport, planned_date, items [{item_code, qty}]."""
	if not _can_create():
		frappe.throw(_("Only purchasing creates transfer orders."), frappe.PermissionError)
	values = frappe.parse_json(values)
	kind, transport = values.get("source_kind"), values.get("transport")
	if kind not in SOURCES:
		frappe.throw(_("Choose the main store or the showroom."))
	if transport not in TRANSPORTS:
		frappe.throw(_("Choose the transport."))
	station = frappe.db.get_value(
		STATION, values.get("station"), ["name", "project", "company"], as_dict=True
	)
	if not station or not station.project:
		frappe.throw(_("Choose a station that has a project."))
	items = _clean_items(values.get("items"))
	day = values.get("planned_date") or nowdate()
	source = warehouse_of(station.company, kind)
	if not source:
		frappe.throw(_("Company {0} has no {1} warehouse.").format(station.company, _(kind)))
	site = site_warehouse(station.project)
	doc = frappe.get_doc(
		{
			"doctype": ORDER,
			"material_request_type": "Material Transfer",
			"company": station.company,
			"transaction_date": nowdate(),
			"schedule_date": day,
			"set_from_warehouse": source,
			"set_warehouse": site,
			"sp_station": station.name,
			"sp_source_kind": kind,
			"sp_transport": transport,
			"sp_transfer_status": CREATED,
			"items": [
				{
					**row,
					"schedule_date": day,
					"from_warehouse": source,
					"warehouse": site,
					"project": station.project,
				}
				for row in items
			],
		}
	)
	doc.flags.ignore_permissions = True  # checked above
	doc.insert()
	doc.submit()
	if transport in (JUMBO, WINCH):
		from smart_power.sp_winch.bookings import expect_transfer_job

		expect_transfer_job(doc.name, station.name, transport, day)
	subject = _("Issue transfer {0} to station {1}").format(doc.name, station.name)
	users = _keepers(source, kind)
	create_task(TASK_ISSUE, ORDER, doc.name, users, subject)
	send(EVENT_ISSUE, users, ORDER, doc.name, subject)
	return doc.name


def _can_refill() -> bool:
	return frappe.session.user == "Administrator" or bool(set(REFILLERS) & set(frappe.get_roles()))


def _company() -> str | None:
	from erpnext import get_default_company

	return frappe.defaults.get_user_default("Company") or get_default_company()


@frappe.whitelist(methods=["POST"])
def request_refill(values: str | dict) -> str:
	"""The showroom asks the main store for items. values: items [{item_code, qty}], planned_date, note."""
	if not _can_refill():
		frappe.throw(_("Only the showroom asks the main store for a refill."), frappe.PermissionError)
	values = frappe.parse_json(values)
	items = _clean_items(values.get("items"))
	company = values.get("company") or _company()
	main, showroom = warehouse_of(company, MAIN), warehouse_of(company, SHOWROOM)
	if not (main and showroom):
		frappe.throw(_("Company {0} needs a main store and a showroom store.").format(company))
	day = values.get("planned_date") or nowdate()
	doc = frappe.get_doc(
		{
			"doctype": ORDER,
			"material_request_type": "Material Transfer",
			"company": company,
			"transaction_date": nowdate(),
			"schedule_date": day,
			"set_from_warehouse": main,
			"set_warehouse": showroom,
			"sp_source_kind": MAIN,
			"sp_transport": OTHER,
			"sp_transfer_status": CREATED,
			"items": [
				{**row, "schedule_date": day, "from_warehouse": main, "warehouse": showroom} for row in items
			],
		}
	)
	doc.flags.ignore_permissions = True  # checked above
	doc.insert()
	doc.submit()
	if values.get("note"):
		doc.add_comment("Comment", values["note"])
	subject = _("Issue refill {0} to the showroom").format(doc.name)
	users = _keepers(main, MAIN)
	create_task(TASK_ISSUE, ORDER, doc.name, users, subject)
	send(EVENT_ISSUE, users, ORDER, doc.name, subject)
	return doc.name


def _destination(doc) -> str:
	"""Where the transfer goes, for its notes and tasks: a station, or the showroom (a refill)."""
	return _("station {0}").format(doc.sp_station) if doc.sp_station else _("the showroom")


def _locked(name: str, *statuses: str):
	status = frappe.db.get_value(ORDER, name, "sp_transfer_status", for_update=True)
	if status not in statuses:
		frappe.throw(_("Transfer {0} is {1}.").format(name, _(status or "not a transfer order")))
	return frappe.get_doc(ORDER, name)


def _check_warehouse(warehouse: str) -> None:
	if not _is_admin() and warehouse not in my_warehouses():
		frappe.throw(_("You do not work at {0}.").format(warehouse), frappe.PermissionError)


def _serials(item_code: str, qty: float, text: str | None) -> str | None:
	"""A serial-tracked item leaves with one serial for each unit."""
	if not _is_serial(item_code):
		return None
	serials = [s.strip() for s in cstr(text).replace(",", "\n").split("\n") if s.strip()]
	if len(set(serials)) != flt(qty):
		frappe.throw(_("{0}: enter {1} different serial numbers.").format(item_code, flt(qty)))
	return "\n".join(serials)


@frappe.whitelist(methods=["POST"])
def issue_transfer(name: str, serials: str | dict | None = None) -> str:
	"""The store hands the goods over: source → Transit. serials: {order row: the unit serials}."""
	doc = _locked(name, CREATED)
	_check_warehouse(doc.set_from_warehouse)
	serials = frappe.parse_json(serials) or {}
	transit = warehouse_of(doc.company, TRANSIT)
	if not transit:
		frappe.throw(_("Company {0} has no transit warehouse.").format(doc.company))
	entry = frappe.get_doc(
		{
			"doctype": ENTRY,
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": doc.company,
			"add_to_transit": 1,
			"from_warehouse": doc.set_from_warehouse,
			"to_warehouse": transit,
			"project": doc.items[0].project,
			"remarks": _("Transfer {0} to {1}").format(doc.name, _destination(doc)),
			"items": [
				{
					"item_code": row.item_code,
					"qty": row.qty,
					"uom": row.uom,
					"stock_uom": row.stock_uom,
					"conversion_factor": row.conversion_factor,
					"s_warehouse": doc.set_from_warehouse,
					"t_warehouse": transit,
					"project": row.project,
					"material_request": doc.name,
					"material_request_item": row.name,
					"use_serial_batch_fields": 1 if _is_serial(row.item_code) else 0,
					"serial_no": _serials(row.item_code, row.qty, serials.get(row.name)),
				}
				for row in doc.items
			],
		}
	)
	entry.flags.ignore_permissions = True

	def post():
		entry.insert()
		entry.submit()

	_as_system(post)
	_signed_by_user(entry.name)
	doc.db_set({"sp_transfer_status": ISSUED, "sp_issue_entry": entry.name})
	close_tasks(ORDER, doc.name, TASK_ISSUE)
	subject = _("Confirm transfer {0} arriving at {1}").format(doc.name, _destination(doc))
	users = _receivers(doc.sp_station) if doc.sp_station else _keepers(doc.set_warehouse, SHOWROOM)
	create_task(TASK_RECEIVE, ORDER, doc.name, users, subject)
	send(EVENT_RECEIVE, users, ORDER, doc.name, subject)
	return entry.name


def _issued_rows(entry: str) -> list:
	return frappe.get_all(
		ENTRY_ROW,
		{"parent": entry},
		["name", "item_code", "item_name", "uom", "transfer_qty", "transferred_qty", "serial_no"],
		order_by="idx asc",
	)


def _left(row) -> float:
	return flt(flt(row.transfer_qty) - flt(row.transferred_qty), QTY_DIGITS)


def _end_transit(source: str, confirmed: dict[str, float], project: str, warehouse: str | None = None):
	"""End Transit for what was counted. A row with nothing confirmed stays in Transit."""
	entry = make_stock_in_entry(source)
	kept = []
	for row in entry.items:
		qty = flt(confirmed.get(row.ste_detail))
		if qty > 0:
			row.qty = qty
			row.transfer_qty = flt(qty * flt(row.conversion_factor or 1), QTY_DIGITS)
			row.project = project
			row.t_warehouse = warehouse or row.t_warehouse
			kept.append(row)
	entry.set("items", kept)
	entry.project = project
	entry.to_warehouse = warehouse or entry.to_warehouse
	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()
	return entry.name


@frappe.whitelist(methods=["POST"])
def confirm_transfer(name: str, lines: str | list) -> dict:
	"""What arrived at the site. lines: [{row: the issue entry's row, qty}]."""
	doc = _locked(name, ISSUED, DISCREPANCY)
	_check_warehouse(doc.set_warehouse)
	lines = frappe.parse_json(lines) if isinstance(lines, str) else lines
	rows = {r.name: r for r in _issued_rows(doc.sp_issue_entry)}
	confirmed: dict[str, float] = {}
	for line in lines or []:
		row = rows.get(line.get("row"))
		qty = flt(line.get("qty"), QTY_DIGITS)
		if not row:
			frappe.throw(_("A line does not belong to transfer {0}.").format(name))
		if qty < 0 or qty > _left(row):
			frappe.throw(_("{0}: only {1} are still in transit.").format(row.item_code, _left(row)))
		if _is_serial(row.item_code) and qty not in (0, _left(row)):
			frappe.throw(_("{0}: confirm all its serial numbers or none.").format(row.item_code))
		confirmed[row.name] = qty
	if not any(confirmed.values()):
		frappe.throw(_("Enter what arrived."))
	entry = _as_system(lambda: _end_transit(doc.sp_issue_entry, confirmed, doc.items[0].project))
	_signed_by_user(entry)
	short = sum(_left(r) for r in _issued_rows(doc.sp_issue_entry))
	close_tasks(ORDER, doc.name, TASK_RECEIVE)
	if short > 0:
		doc.db_set("sp_transfer_status", DISCREPANCY)
		subject = _("Transfer {0}: {1} still in transit after the site's count").format(doc.name, flt(short))
		users = sorted({*_holders(BUYER), doc.owner} - {"Administrator"}) or [doc.owner]
		create_task(TASK_DIFFERENCE, ORDER, doc.name, users, subject)
		send(EVENT_DIFFERENCE, users, ORDER, doc.name, subject)
		return {"entry": entry, "status": DISCREPANCY, "short": flt(short)}
	doc.db_set("sp_transfer_status", RECEIVED)
	close_tasks(ORDER, doc.name, TASK_DIFFERENCE)
	return {"entry": entry, "status": RECEIVED, "short": 0}


@frappe.whitelist(methods=["POST"])
def cancel_transfer(name: str) -> str:
	"""Only before the store has issued it."""
	if not _can_create():
		frappe.throw(_("Only purchasing cancels transfer orders."), frappe.PermissionError)
	doc = _locked(name, CREATED)
	doc.flags.ignore_permissions = True
	doc.cancel()
	doc.db_set("sp_transfer_status", CANCELLED)
	close_tasks(ORDER, doc.name, TASK_ISSUE)
	from smart_power.sp_winch.bookings import cancel_transfer_job

	cancel_transfer_job(doc.name)
	return doc.name


# --- the screens ---------------------------------------------------------------------------------


def _card(row) -> dict:
	lines = frappe.get_all(
		"Material Request Item",
		{"parent": row.name},
		["name", "item_code", "item_name", "uom", "qty"],
		order_by="idx asc",
	)
	for line in lines:
		line.serial = _is_serial(line.item_code)
	return {**row, "owner_name": get_fullname(row.owner), "lines": lines}


FIELDS = [
	"name", "owner", "sp_station as station", "sp_source_kind as source_kind", "sp_transport as transport",
	"sp_transfer_status as status", "sp_issue_entry as issue_entry", "set_from_warehouse as source",
	"set_warehouse as site", "schedule_date", "transaction_date",
]  # fmt: skip


@frappe.whitelist()
def my_transfers() -> dict:
	"""The transfers this user works on: purchasing sees all of them, a store those it issues."""
	user = frappe.session.user
	mine = set(my_warehouses(user))
	sees_all = _can_create()
	rows = frappe.get_all(
		ORDER,
		{"sp_transfer_status": ("is", "set")},
		FIELDS,
		order_by="creation desc",
		limit=RECENT,
	)
	return {
		"can_create": sees_all,
		"can_refill": _can_refill(),
		"transfers": [
			{**_card(r), "can_issue": r.status == CREATED and (_is_admin(user) or r.source in mine)}
			for r in rows
			# a store sees what it issues, and the showroom the refills it asked for
			if sees_all or r.source in mine or r.site in mine or r.owner == user
		],
	}


@frappe.whitelist()
def transfers_to_confirm() -> list[dict]:
	"""What is on its way to my sites, with what is still in transit on each line."""
	mine = my_warehouses()
	rows = frappe.get_all(
		ORDER,
		{"sp_transfer_status": ("in", (ISSUED, DISCREPANCY)), "set_warehouse": ("in", mine or [""])},
		FIELDS,
		order_by="creation asc",
	)
	cards = []
	for row in rows:
		lines = [
			{
				"row": r.name,
				"item_code": r.item_code,
				"item_name": r.item_name,
				"uom": r.uom,
				"left": _left(r),
				"serial": _is_serial(r.item_code),
				"serial_no": r.serial_no,
			}
			for r in _issued_rows(row.issue_entry)
			if _left(r) > 0
		]
		cards.append({**row, "lines": lines})
	return cards


@frappe.whitelist()
def transfer_options() -> dict:
	if not _can_create():
		frappe.throw(_("Only purchasing creates transfer orders."), frappe.PermissionError)
	return {"sources": SOURCES, "transports": TRANSPORTS}


def transfer_print(doc) -> frappe._dict:
	"""What the transfer note prints: quantities and serials, never a price."""
	from smart_power.sp_core.printing import ar_date

	order = next((r.material_request for r in doc.items if r.material_request), None)
	values = (
		frappe.db.get_value(ORDER, order, ["sp_station", "sp_transport", "set_warehouse"], as_dict=True) or {}
		if order
		else {}
	)
	return frappe._dict(
		no=doc.name,
		order=order,
		date=ar_date(doc.posting_date),
		source=doc.from_warehouse or (doc.items[0].s_warehouse if doc.items else ""),
		site=values.get("set_warehouse"),
		station=values.get("sp_station"),
		transport=values.get("sp_transport"),
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
