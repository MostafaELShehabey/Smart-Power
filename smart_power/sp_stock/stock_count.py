"""Stock counts (SP-94, I5): a count sheet per location, on the admin's schedule, approved by the admin.

Company stock only: the supplier's consignment is checked in the consignment reconciliation
(SP-93), never through a count (data model note 8-11-2026).

    seed_count_schedule(company)  the main store monthly and the showroom store weekly (the seed)
    create_scheduled_counts()     daily: a draft per scheduled location, once a week or month
    start_count(warehouse, blind) a count started by hand
    sheet(name)                   the lines to count; a blind count never sends the system quantity
    save_counts(name, lines)      what was counted so far (by typing or by barcode)
    submit_count(name)            system vs counted; differences go to the admin as a task
    approve_count(name, reason)   a Stock Reconciliation by the difference, today, and the audit log
    reject_count(name, reason)    a new sheet to count again, for the same store keeper

The difference is posted on approval as today's stock plus the difference, so what moved after
the count is kept (owner, 2026-11-20).
"""

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	add_months,
	flt,
	get_first_day,
	get_first_day_of_week,
	get_fullname,
	getdate,
	now_datetime,
	nowdate,
	nowtime,
)

from smart_power.sp_core.inbox import close_tasks, create_task
from smart_power.sp_core.services.audit import audit
from smart_power.sp_core.services.settings import get_settings
from smart_power.sp_stock.goods_receipt import QTY_DIGITS, STORE_ROLES, my_warehouses
from smart_power.sp_stock.warehouses import MAIN, SHOWROOM, TRANSIT, warehouse_of

COUNT = "SP Stock Count"
DRAFT, SUBMITTED, APPROVED, REJECTED = "Draft", "Submitted", "Approved", "Rejected"
WEEK, MONTH = "Week", "Month"
TASK_COUNT, TASK_DIFFERENCE = "Stock Count", "Count Difference"
APPROVER = "SP Admin"
APPROVERS = (APPROVER, "System Manager")
DAYS_IN_WEEK = 7  # sp-allow-number: calendar
MONEY_DIGITS = 2  # sp-allow-number: money to the piaster
SCHEDULE_SEED = "count_schedule"


def is_approver(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(APPROVERS) & set(frappe.get_roles(user)))


def _can_count(warehouse: str, user: str | None = None) -> bool:
	return is_approver(user) or warehouse in my_warehouses(user)


def _check_counter(doc):
	if not _can_count(doc.warehouse):
		frappe.throw(_("You do not count stock at {0}.").format(doc.warehouse), frappe.PermissionError)


def _check_approver():
	if not is_approver():
		frappe.throw(_("Only the admin decides on count differences."), frappe.PermissionError)


def validate_count(doc):
	if doc.warehouse and frappe.db.get_value("Warehouse", doc.warehouse, "is_group"):
		frappe.throw(_("Count a store, not the group {0}.").format(doc.warehouse))
	seen = set()
	for line in doc.lines:
		if line.item_code in seen:
			frappe.throw(_("Row {0}: {1} is already on the sheet.").format(line.idx, line.item_code))
		seen.add(line.item_code)
		if flt(line.counted_qty) < 0:
			frappe.throw(_("Row {0}: a counted quantity cannot be negative.").format(line.idx))


# ---------------------------------------------------------------- schedule


def seed_count_schedule(company: str) -> None:
	"""The seed's schedule for this company's main and showroom stores, where they are missing."""
	from smart_power.sp_core.setup.seed import defaults

	seed = defaults().get(SCHEDULE_SEED, {})
	settings = frappe.get_single("Smart Power Settings")
	have = {row.warehouse for row in settings.count_schedule}
	added = False
	for kind in (MAIN, SHOWROOM):
		warehouse = warehouse_of(company, kind)
		if warehouse and warehouse not in have and kind in seed:
			settings.append("count_schedule", {"warehouse": warehouse, **seed[kind]})
			added = True
	if added:
		settings.flags.ignore_permissions = True
		settings.flags.sp_seed = True
		settings.save()


def period_start(every: str, day=None):
	day = getdate(day or nowdate())
	return get_first_day_of_week(day) if every == WEEK else get_first_day(day)


def next_period(every: str, day=None):
	start = period_start(every, day)
	return add_days(start, DAYS_IN_WEEK) if every == WEEK else add_months(start, 1)


def _counted_since(warehouse: str, start) -> bool:
	return bool(frappe.db.exists(COUNT, {"warehouse": warehouse, "count_date": (">=", start)}))


def _counters(warehouse: str) -> list[str]:
	"""The store keepers of a location: its responsible user, else the holders of its role."""
	from smart_power.sp_stock.transfers import _holders

	responsible, kind = frappe.db.get_value("Warehouse", warehouse, ["sp_responsible_user", "warehouse_type"])
	if responsible:
		return [responsible]
	return _holders(STORE_ROLES[kind]) if kind in STORE_ROLES else []


def create_scheduled_counts() -> list[str]:
	"""Daily: each scheduled location gets one sheet a week or a month, and its keeper a task."""
	made = []
	for row in get_settings().count_schedule:
		if frappe.db.get_value("Warehouse", row.warehouse, "disabled"):
			continue
		if _counted_since(row.warehouse, period_start(row.every)):
			continue
		made.append(_new_count(row.warehouse, row.blind, scheduled=1).name)
	return made


def _items_at(warehouse: str) -> list[str]:
	"""What the books hold at a location: the sheet starts from it, and the keeper adds what else he finds."""
	return frappe.get_all(
		"Bin",
		{"warehouse": warehouse, "actual_qty": ("!=", 0)},
		pluck="item_code",
		order_by="item_code asc",
	)


def _new_count(warehouse: str, blind, scheduled=0, recount_of=None, users=None):
	doc = frappe.get_doc(
		{
			"doctype": COUNT,
			"warehouse": warehouse,
			"count_date": nowdate(),
			"blind": 1 if blind else 0,
			"scheduled": scheduled,
			"recount_of": recount_of,
			"lines": [{"item_code": item} for item in _items_at(warehouse)],
		}
	)
	doc.flags.ignore_permissions = True  # the caller has checked who may start it
	doc.insert()
	subject = (
		_("Count {0} again at {1}").format(doc.name, warehouse)
		if recount_of
		else _("Stock count {0} at {1}").format(doc.name, warehouse)
	)
	create_task(TASK_COUNT, COUNT, doc.name, users or _counters(warehouse), subject)
	return doc


def next_counts(user: str | None = None) -> list[dict]:
	"""The scheduled locations this user counts: when the next count is due (today if one is open)."""
	mine = set(my_warehouses(user))
	rows = []
	for row in get_settings().count_schedule:
		if row.warehouse not in mine:
			continue
		open_count = frappe.db.get_value(COUNT, {"warehouse": row.warehouse, "status": DRAFT}, "name")
		due = (
			getdate(nowdate())
			if open_count or not _counted_since(row.warehouse, period_start(row.every))
			else next_period(row.every)
		)
		rows.append({"warehouse": row.warehouse, "every": row.every, "due": due, "open": open_count})
	return sorted(rows, key=lambda r: r["due"])


# ---------------------------------------------------------------- the sheet


@frappe.whitelist(methods=["POST"])
def start_count(warehouse: str, blind: int | str = 1) -> str:
	if not _can_count(warehouse):
		frappe.throw(_("You do not count stock at {0}.").format(warehouse), frappe.PermissionError)
	return _new_count(warehouse, int(blind or 0), users=[frappe.session.user]).name


def _system_qty(item_code: str, warehouse: str) -> float:
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))


@frappe.whitelist()
def sheet(name: str) -> dict:
	"""The lines to count. A blind count never sends the system quantity before it is submitted."""
	doc = frappe.get_doc(COUNT, name)
	_check_counter(doc)
	hide = doc.blind and doc.status == DRAFT
	lines = []
	for line in doc.lines:
		row = {
			"item_code": line.item_code,
			"item_name": line.item_name,
			"uom": line.uom,
			"counted": line.counted,
			"counted_qty": line.counted_qty if line.counted else None,
			"note": line.note,
		}
		if not hide:
			row["system_qty"] = (
				_system_qty(line.item_code, doc.warehouse) if doc.status == DRAFT else line.system_qty
			)
			row["diff"] = line.diff if doc.status != DRAFT else None
		lines.append(row)
	return {
		"name": doc.name,
		"warehouse": doc.warehouse,
		"count_date": doc.count_date,
		"status": doc.status,
		"blind": doc.blind,
		"reason": doc.reason,
		"stock_reconciliation": doc.stock_reconciliation,
		"can_edit": doc.status == DRAFT,
		"lines": lines,
	}


@frappe.whitelist()
def find_item(code: str) -> dict | None:
	"""A scanned barcode or a typed item code, as the item to count."""
	code = (code or "").strip()
	if not code:
		return None
	item = frappe.db.get_value("Item Barcode", {"barcode": code}, "parent") or frappe.db.exists("Item", code)
	if not item:
		return None
	return frappe.db.get_value(
		"Item", item, ["name as item_code", "item_name", "stock_uom as uom"], as_dict=True
	)


def _locked(name: str, *statuses: str):
	status = frappe.db.get_value(COUNT, name, "status", for_update=True)
	if status not in statuses:
		frappe.throw(_("Count {0} is {1}.").format(name, _(status or "missing")))
	return frappe.get_doc(COUNT, name)


@frappe.whitelist(methods=["POST"])
def save_counts(name: str, lines: str | list) -> dict:
	"""lines: [{item_code, counted_qty, note}]; an item not yet on the sheet is added to it.
	An empty quantity clears the line (not counted)."""
	doc = _locked(name, DRAFT)
	_check_counter(doc)
	by_item = {line.item_code: line for line in doc.lines}
	for row in frappe.parse_json(lines) or []:
		item = row.get("item_code")
		if not item:
			continue
		line = by_item.get(item) or doc.append("lines", {"item_code": item})
		by_item[item] = line
		qty = row.get("counted_qty")
		line.counted = 0 if qty in (None, "") else 1
		line.counted_qty = flt(qty, QTY_DIGITS) if line.counted else 0
		if "note" in row:
			line.note = row.get("note")
	doc.flags.ignore_permissions = True  # checked above
	doc.save()
	return sheet(name)


@frappe.whitelist(methods=["POST"])
def submit_count(name: str) -> dict:
	"""System vs counted, taken now. Every line must be counted (a zero is typed, never assumed)."""
	doc = _locked(name, DRAFT)
	_check_counter(doc)
	missing = [line.item_name or line.item_code for line in doc.lines if not line.counted]
	if missing:
		frappe.throw(
			_("Count every line before submitting (an empty shelf is 0): {0}").format(", ".join(missing))
		)
	if not doc.lines:
		frappe.throw(_("The sheet has no lines."))
	for line in doc.lines:
		line.system_qty = _system_qty(line.item_code, doc.warehouse)
		line.diff = flt(line.counted_qty - line.system_qty, QTY_DIGITS)
	doc.differences = sum(1 for line in doc.lines if line.diff)
	doc.status = SUBMITTED
	doc.counted_by = frappe.session.user
	doc.submitted_on = now_datetime()
	doc.flags.ignore_permissions = True
	doc.save()
	close_tasks(COUNT, doc.name, TASK_COUNT)
	if doc.differences:
		from smart_power.sp_sales.quote_request import _users_with

		create_task(
			TASK_DIFFERENCE,
			COUNT,
			doc.name,
			_users_with(APPROVER),
			_("Count {0} at {1}: {2} differences to approve").format(
				doc.name, doc.warehouse, doc.differences
			),
		)
	else:
		_decide(doc, APPROVED, _("No differences"))
	return {"status": doc.status, "differences": doc.differences}


# ---------------------------------------------------------------- the admin's decision


def _decide(doc, status: str, reason: str, reconciliation: str | None = None):
	doc.status = status
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.reason = reason
	doc.stock_reconciliation = reconciliation
	doc.flags.ignore_permissions = True
	doc.save()
	close_tasks(COUNT, doc.name, TASK_DIFFERENCE)
	audit(
		f"Stock count {status.lower()}",
		COUNT,
		doc.name,
		warehouse=doc.warehouse,
		reason=reason,
		stock_reconciliation=reconciliation,
		lines=[
			{"item_code": l.item_code, "system": l.system_qty, "counted": l.counted_qty, "diff": l.diff}
			for l in doc.lines
			if l.diff
		],
	)


def _rate(item_code: str, warehouse: str, company: str) -> float:
	"""The item's cost here, else its latest cost in the company (an item found where the books
	hold none), else the Item's own rate."""
	rate = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"))
	if rate:
		return rate
	latest = frappe.get_all(
		"Stock Ledger Entry",
		{"item_code": item_code, "company": company, "is_cancelled": 0, "valuation_rate": (">", 0)},
		pluck="valuation_rate",
		order_by="posting_date desc, posting_time desc, creation desc",
		limit=1,
	)
	if latest:
		return flt(latest[0])
	rate = flt(frappe.db.get_value("Item", item_code, "valuation_rate"))
	if rate:
		return rate
	from erpnext.stock.stock_ledger import get_valuation_rate

	return flt(
		get_valuation_rate(
			item_code,
			warehouse,
			"Stock Reconciliation",
			None,
			True,
			company=company,
			raise_error_if_no_rate=False,
		)
	)


def _reconcile(doc) -> str:
	"""A Stock Reconciliation by the difference, today: the books move by exactly what the count found."""
	from smart_power.sp_finance.centers import SHOWROOM as SHOWROOM_CENTER
	from smart_power.sp_finance.centers import center

	kind = frappe.db.get_value("Warehouse", doc.warehouse, "warehouse_type")
	items = []
	for line in doc.lines:
		if not line.diff:
			continue
		if frappe.get_cached_value("Item", line.item_code, "has_serial_no") or frappe.get_cached_value(
			"Item", line.item_code, "has_batch_no"
		):
			frappe.throw(
				_(
					"{0} has serial or batch numbers: correct its stock by hand in a Stock Reconciliation."
				).format(line.item_code)
			)
		qty = flt(_system_qty(line.item_code, doc.warehouse) + line.diff, QTY_DIGITS)
		if qty < 0:
			frappe.throw(
				_("{0}: the stock moved since the count, and the difference would leave {1}.").format(
					line.item_code, qty
				)
			)
		items.append(
			{
				"item_code": line.item_code,
				"warehouse": doc.warehouse,
				"qty": qty,
				"valuation_rate": _rate(line.item_code, doc.warehouse, doc.company),
			}
		)
	reconciliation = frappe.get_doc(
		{
			"doctype": "Stock Reconciliation",
			"company": doc.company,
			"purpose": "Stock Reconciliation",
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"set_posting_time": 1,
			"expense_account": frappe.get_cached_value("Company", doc.company, "stock_adjustment_account"),
			"cost_center": center(SHOWROOM_CENTER, doc.company)
			if kind == SHOWROOM
			else frappe.get_cached_value("Company", doc.company, "cost_center"),
			"items": items,
		}
	)
	reconciliation.flags.ignore_permissions = True  # the admin decided it
	reconciliation.insert()
	reconciliation.submit()
	return reconciliation.name


@frappe.whitelist(methods=["POST"])
def approve_count(name: str, reason: str) -> dict:
	_check_approver()
	if not (reason or "").strip():
		frappe.throw(_("Give the reason for the differences."))
	doc = _locked(name, SUBMITTED)
	reconciliation = _reconcile(doc) if doc.differences else None
	_decide(doc, APPROVED, reason.strip(), reconciliation)
	return {"status": doc.status, "stock_reconciliation": reconciliation}


@frappe.whitelist(methods=["POST"])
def reject_count(name: str, reason: str) -> dict:
	"""The stock is not changed; the store keeper who counted gets a new sheet to count again."""
	_check_approver()
	if not (reason or "").strip():
		frappe.throw(_("Give the reason for rejecting the count."))
	doc = _locked(name, SUBMITTED)
	_decide(doc, REJECTED, reason.strip())
	recount = _new_count(
		doc.warehouse, doc.blind, scheduled=doc.scheduled, recount_of=doc.name, users=[doc.counted_by]
	)
	return {"status": doc.status, "recount": recount.name}


@frappe.whitelist()
def my_counts() -> dict:
	"""The counts this user works on: open sheets at their locations, and for the admin the
	differences to decide. Values show only to those who may see cost."""
	from smart_power.permissions import can_see_cost

	user = frappe.session.user
	approver = is_approver(user)
	mine = my_warehouses(user)
	fields = ["name", "warehouse", "count_date", "status", "blind", "scheduled", "differences", "reason"]
	open_counts = frappe.get_all(
		COUNT,
		{"status": DRAFT, **({} if approver else {"warehouse": ("in", mine or [""])})},
		fields,
		order_by="count_date asc, creation asc",
	)
	to_decide = []
	if approver:
		see_cost = can_see_cost(user)
		for row in frappe.get_all(COUNT, {"status": SUBMITTED}, fields, order_by="submitted_on asc"):
			doc = frappe.get_doc(COUNT, row.name)
			row.lines = [
				{
					"item_code": l.item_code,
					"item_name": l.item_name,
					"uom": l.uom,
					"system_qty": l.system_qty,
					"counted_qty": l.counted_qty,
					"diff": l.diff,
					"note": l.note,
					**(
						{"value": flt(l.diff * _rate(l.item_code, doc.warehouse, doc.company), MONEY_DIGITS)}
						if see_cost
						else {}
					),
				}
				for l in doc.lines
				if l.diff
			]
			row.counted_by = doc.counted_by
			row.counted_by_name = get_fullname(doc.counted_by)
			to_decide.append(row)
	recent = frappe.get_all(
		COUNT,
		{
			"status": ("in", (SUBMITTED, APPROVED, REJECTED)),
			**({} if approver else {"warehouse": ("in", mine or [""])}),
		},
		[*fields, "stock_reconciliation"],
		order_by="modified desc",
		limit=10,  # sp-allow-number: a screenful of the latest counts
	)
	return {
		"approver": approver,
		"locations": frappe.get_all(
			"Warehouse",
			{"name": ("in", mine or [""]), "is_group": 0, "warehouse_type": ("!=", TRANSIT)},
			pluck="name",
			order_by="name asc",
		),
		"next": next_counts(user),
		"open": open_counts,
		"to_decide": to_decide,
		"recent": recent,
	}
