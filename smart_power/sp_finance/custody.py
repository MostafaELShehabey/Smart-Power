"""Custody A9 (SP-122; journey J7; ERD 7.4: Custody → Custody Line, Custody Settlement).

    Given → Spending → Settlement submitted → Approved → Returned or Carried

- The admin gives custody from an official account to the holder's custody account
  (Dr custody / Cr official), posted at once.
- The holder records each expense on the custody: date, amount, type, where it lands (a station,
  a center, or a center's petty cash), receipt photo and note. Local purchases are expenses too.
- The holder submits a settlement (a group of expenses) with what to do with the leftover cash:
  carry it to the next period, or return it to an official account. The settlement waits in A1.
- The admin approves: each approved expense posts Dr its expense account (from the expense type)
  on its center, with the station's project for a station / Cr the custody account. A rejected
  expense goes back to the holder with the reason; the rest are approved. "Return" then moves
  the holder's whole custody balance back to the official account (Dr official / Cr custody).
- The holder sees only their own custody (and the admin all).
"""

import json

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.utils import flt, getdate, now_datetime, today

from smart_power.sp_finance.accounts import CUSTODY, OFFICIAL

CUS, LINE, SETTLEMENT, TASK = "SP Custody", "SP Custody Line", "SP Custody Settlement", "SP Task"
GIVEN, SPENDING, SUBMITTED, APPROVED, RETURNED, CARRIED, CANCELLED = (
	"Given",
	"Spending",
	"Settlement submitted",
	"Approved",
	"Returned",
	"Carried",
	"Cancelled",
)
DRAFT, IN_SETTLEMENT, LINE_APPROVED, LINE_REJECTED = "Draft", "In settlement", "Approved", "Rejected"
PENDING, REJECTED = "Pending", "Rejected"
STATION, CENTER, PETTY = "Station", "Center", "Petty cash"
RETURN, CARRY = "Return", "Carry"
OPEN = (GIVEN, SPENDING, SUBMITTED, APPROVED, CARRIED)
ADMIN_ROLE, ADMIN_ROLES = "SP Admin", ("SP Admin", "System Manager")
SEES_ALL = (*ADMIN_ROLES, "SP Accountant", "Accounts Manager")
PETTY_ACCOUNT = "Petty Cash Expenses"
CONFIRM_TASK, TASK_OPEN, TASK_DONE = "Receipt to Confirm", "Open", "Done"
EXPENSE_EVENT = "Custody Expense"
KIND = "Custody settlement"
ROUNDING = 0.005  # sp-allow-number: half a piastre


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def sees_all(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(SEES_ALL) & set(frappe.get_roles(user)))


def _kind(account: str | None) -> str | None:
	return frappe.db.get_value("Account", account, "sp_account_kind") if account else None


def _balance(account: str, company: str) -> float:
	from erpnext.accounts.utils import get_balance_on

	return flt(get_balance_on(account, company=company, ignore_account_permission=True))


# --- the custody given -------------------------------------------------------------------------


def validate(doc) -> None:
	from smart_power.sp_finance.accounts import holder_account

	if flt(doc.amount) <= 0:
		frappe.throw(_("The amount must be above zero."))
	if _kind(doc.from_account) != OFFICIAL:
		frappe.throw(_("Custody is given from an official account (a bank, the Post, InstaPay …)."))
	doc.custody_account = holder_account(doc.holder, CUSTODY, doc.company)
	if doc.docstatus.is_draft():
		doc.status = "Draft"
	_totals(doc)


def _totals(doc) -> None:
	doc.spent_amount = sum(flt(r.amount) for r in doc.lines if r.status != LINE_REJECTED)
	doc.approved_amount = sum(flt(r.amount) for r in doc.lines if r.status == LINE_APPROVED)
	if doc.custody_account and not doc.is_new():
		doc.balance = _balance(doc.custody_account, doc.company)


def on_submit(doc) -> None:
	if not is_admin():
		frappe.throw(_("Only the admin gives custody."), frappe.PermissionError)
	entry = _journal(
		doc,
		doc.given_on,
		[
			{"account": doc.custody_account, "debit_in_account_currency": flt(doc.amount)},
			{"account": doc.from_account, "credit_in_account_currency": flt(doc.amount)},
		],
		"Custody Given",
		_("Custody {0} to {1}").format(doc.name, doc.holder_name or doc.holder),
	)
	doc.db_set({"journal_entry": entry, "status": GIVEN})
	doc.db_set("balance", _balance(doc.custody_account, doc.company))
	_notify(doc.holder, CUS, doc.name, _("You have been given custody of {0}").format(_money(doc.amount)))


def on_cancel(doc) -> None:
	"""Its entries are cancelled with it (SP-113's hook)."""
	doc.db_set("status", CANCELLED)


def _journal(source, posting_date, accounts: list[dict], event: str, remark: str) -> str:
	center = frappe.get_cached_value("Company", source.company, "cost_center")
	for row in accounts:
		row.setdefault("cost_center", center)
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": source.company,
			"posting_date": posting_date or today(),
			"user_remark": remark,
			"sp_posting_event": event,
			"sp_source_doctype": source.doctype,
			"sp_source_name": source.name,
			"accounts": accounts,
		}
	)
	je.flags.ignore_permissions = True  # who may post is checked by the caller
	je.insert()
	je.submit()
	return je.name


# --- the holder's expenses -----------------------------------------------------------------------


def _own_custody(name: str):
	doc = frappe.get_doc(CUS, name)
	if doc.holder != frappe.session.user and not is_admin():
		frappe.throw(_("This is not your custody."), frappe.PermissionError)
	if doc.docstatus != 1 or doc.status in (RETURNED, CANCELLED):
		frappe.throw(_("Custody {0} is closed.").format(name))
	return doc


def _check_line(values: dict, company: str) -> dict:
	amount = flt(values.get("amount"))
	if amount <= 0:
		frappe.throw(_("The amount must be above zero."))
	expense_type = values.get("expense_type")
	if frappe.db.get_value("SP List Value", expense_type, "list_name") != "Expense Type":
		frappe.throw(_("Choose the expense type."))
	on = values.get("center_type")
	row = {
		"work_date": getdate(values.get("work_date") or today()),
		"amount": amount,
		"expense_type": expense_type,
		"center_type": on,
		"receipt_photo": values.get("receipt_photo"),
		"note": values.get("note"),
		"client_uuid": values.get("client_uuid"),
	}
	if on == STATION:
		station = frappe.db.get_value("SP Station", values.get("station"), ["name", "company"], as_dict=True)
		if not station or station.company != company:
			frappe.throw(_("Choose the station."))
		row["station"] = station.name
	elif on in (CENTER, PETTY):
		center = frappe.db.get_value(
			"Cost Center", values.get("cost_center"), ["name", "company", "is_group"], as_dict=True
		)
		if not center or center.company != company or center.is_group:
			frappe.throw(_("Choose the center."))
		row["cost_center"] = center.name
	else:
		frappe.throw(_("Choose where the expense lands: a station, a center or petty cash."))
	return row


@frappe.whitelist(methods=["POST"])
def add_expense(custody: str, values: str | dict) -> str:
	"""The holder records one expense on their custody (the same mobile id is saved once)."""
	values = frappe.parse_json(values)
	doc = _own_custody(custody)
	uuid = values.get("client_uuid")
	if uuid:
		existing = next((r for r in doc.lines if r.client_uuid == uuid), None)
		if existing:
			return existing.name
	row = doc.append(
		"lines", {**_check_line(values, doc.company), "status": DRAFT, "entry_time": now_datetime()}
	)
	if doc.status in (GIVEN, APPROVED, CARRIED):
		doc.status = SPENDING
	_totals(doc)
	doc.flags.ignore_permissions = True  # checked by _own_custody
	doc.save()
	return row.name


@frappe.whitelist(methods=["POST"])
def remove_expense(custody: str, line: str) -> None:
	"""A draft or rejected expense the holder takes back."""
	doc = _own_custody(custody)
	row = next((r for r in doc.lines if r.name == line), None)
	if not row or row.status not in (DRAFT, LINE_REJECTED):
		frappe.throw(_("Only a draft or rejected expense is removed."))
	doc.remove(row)
	_totals(doc)
	doc.flags.ignore_permissions = True
	doc.save()


@frappe.whitelist(methods=["POST"])
def submit_settlement(
	custody: str,
	lines: str | list | None = None,
	leftover_action: str = CARRY,
	return_to_account: str | None = None,
) -> str:
	"""The holder submits a settlement: the chosen draft or rejected expenses (all of them by default)."""
	doc = _own_custody(custody)
	chosen = frappe.parse_json(lines) if isinstance(lines, str) else lines
	rows = [r for r in doc.lines if r.status in (DRAFT, LINE_REJECTED) and (not chosen or r.name in chosen)]
	if not rows:
		frappe.throw(_("There are no expenses to settle."))
	settlement = frappe.get_doc(
		{
			"doctype": SETTLEMENT,
			"custody": doc.name,
			"leftover_action": leftover_action,
			"return_to_account": return_to_account if leftover_action == RETURN else None,
			"lines": [
				{
					"line": r.name,
					"work_date": r.work_date,
					"amount": r.amount,
					"expense_type": r.expense_type,
					"center_type": r.center_type,
					"center": _where(r),
					"station": r.station,
					"cost_center": r.cost_center,
					"receipt_photo": r.receipt_photo,
					"note": r.note,
				}
				for r in rows
			],
		}
	)
	settlement.flags.ignore_permissions = True  # checked by _own_custody: the holder's own
	settlement.insert()
	settlement.submit()
	return settlement.name


def _where(row) -> str:
	if row.center_type == STATION:
		return _("Station {0}").format(row.station)
	if row.center_type == PETTY:
		return _("Petty cash of {0}").format(row.cost_center)
	return row.cost_center or ""


# --- the settlement ----------------------------------------------------------------------------


def validate_settlement(doc) -> None:
	custody = frappe.get_doc(CUS, doc.custody)
	doc.holder, doc.holder_name = custody.holder, custody.holder_name
	doc.company, doc.custody_account = custody.company, custody.custody_account
	if doc.is_new() or not doc.recorded_by:
		doc.recorded_by = frappe.session.user
	if doc.docstatus.is_draft():
		doc.status = "Draft"
		rows = {r.name: r for r in custody.lines}
		for line in doc.lines:
			row = rows.get(line.line)
			if not row or row.status not in (DRAFT, LINE_REJECTED):
				frappe.throw(_("Row {0}: this expense is not open for a settlement.").format(line.idx))
	if not doc.lines:
		frappe.throw(_("A settlement needs at least one expense."))
	doc.total = sum(flt(r.amount) for r in doc.lines)
	dates = [getdate(r.work_date) for r in doc.lines if r.work_date]
	doc.period_from, doc.period_to = (min(dates), max(dates)) if dates else (None, None)
	if doc.leftover_action == RETURN and _kind(doc.return_to_account) != OFFICIAL:
		frappe.throw(_("Return the leftover to an official account."))


def on_settlement_submit(doc) -> None:
	from smart_power.sp_sales.quote_request import _users_with

	doc.db_set("status", PENDING)
	_mark_lines(
		doc, IN_SETTLEMENT, settlement=doc.name, reasons={}
	)  # a resubmitted expense drops its old reason
	frappe.db.set_value(CUS, doc.custody, "status", SUBMITTED)
	for admin in _users_with(ADMIN_ROLE) or ["Administrator"]:
		frappe.get_doc(
			{
				"doctype": TASK,
				"subject": _("Approve the custody settlement of {0}: {1}").format(
					doc.holder_name or doc.holder, _money(doc.total)
				),
				"task_type": CONFIRM_TASK,
				"assigned_to": admin,
				"reference_doctype": SETTLEMENT,
				"reference_name": doc.name,
			}
		).insert(ignore_permissions=True)


def on_settlement_cancel(doc) -> None:
	if doc.status == PENDING:
		doc.db_set("status", REJECTED)
	_close_tasks(doc)


def _mark_lines(doc, status: str, settlement: str | None = None, reasons: dict | None = None) -> None:
	for line in doc.lines:
		values = {"status": status, "settlement": settlement}
		if reasons is not None:
			values["reject_reason"] = reasons.get(line.line)
		frappe.db.set_value(LINE, line.line, values, update_modified=False)


def _pending(name: str):
	if not is_admin():
		frappe.throw(_("Only the admin approves a custody settlement."), frappe.PermissionError)
	doc = frappe.get_doc(SETTLEMENT, name)
	if doc.status != PENDING:
		frappe.throw(_("Settlement {0} is {1}, not pending.").format(name, _(doc.status)))
	return doc


def expense_account(line, company: str) -> str:
	"""The expense type's account (its meta), petty cash's own account, else the Account Map's."""
	from smart_power.sp_core.services.settings import account_map

	name = None
	if line.get("center_type") == PETTY:
		name = PETTY_ACCOUNT
	else:
		meta = frappe.db.get_value("SP List Value", line.expense_type, "meta_json")
		meta = json.loads(meta) if isinstance(meta, str) and meta else (meta or {})
		name = meta.get("account")
	if name:
		account = frappe.db.get_value(
			"Account", {"company": company, "account_name": name, "is_group": 0}
		) or frappe.db.get_value("Account", {"company": company, "name": name, "is_group": 0})
		if account:
			return account
	row = account_map(EXPENSE_EVENT)
	if row and row.debit_account:
		return row.debit_account
	frappe.throw(
		_(
			"Set the account of expense type {0} (Lists) or the Custody Expense row of the Account Map."
		).format(frappe.bold(line.expense_type))
	)


def _expense_lines(doc, rows) -> list[dict]:
	from smart_power.sp_finance.centers import station_center

	out = []
	for r in rows:
		line = {
			"account": expense_account(r, doc.company),
			"debit_in_account_currency": flt(r.amount),
			"user_remark": r.note,
		}
		if r.station:
			line["cost_center"] = station_center(doc.company)
			line["project"] = frappe.db.get_value("SP Station", r.station, "project")
		else:
			line["cost_center"] = r.cost_center
		out.append(line)
	total = sum(flt(r.amount) for r in rows)
	out.append({"account": doc.custody_account, "credit_in_account_currency": total})
	return out


@frappe.whitelist(methods=["POST"])
def confirm(name: str) -> str | None:
	"""Approve: the approved expenses post to their centers; rejected ones go back with the reason;
	"Return" moves the holder's custody balance back to the official account."""
	doc = _pending(name)
	rejected = [r for r in doc.lines if r.decision == "Reject"]
	for r in rejected:
		if not (r.reject_reason or "").strip():
			frappe.throw(_("Row {0}: give the reason for rejecting it.").format(r.idx))
	approved = [r for r in doc.lines if r.decision != "Reject"]
	entry = None
	if approved:
		entry = _journal(
			doc,
			doc.period_to or today(),
			_expense_lines(doc, approved),
			"Custody Settlement",
			_("Custody settlement {0} of {1}").format(doc.name, doc.holder_name or doc.holder),
		)
	for r in approved:
		frappe.db.set_value(
			LINE, r.line, {"status": LINE_APPROVED, "settlement": doc.name}, update_modified=False
		)
	for r in rejected:
		frappe.db.set_value(
			LINE,
			r.line,
			{"status": LINE_REJECTED, "reject_reason": r.reject_reason, "settlement": None},
			update_modified=False,
		)
	returned, return_entry = 0.0, None
	if doc.leftover_action == RETURN:
		returned = _balance(doc.custody_account, doc.company)
		if returned > ROUNDING:
			return_entry = _journal(
				doc,
				today(),
				[
					{"account": doc.return_to_account, "debit_in_account_currency": returned},
					{"account": doc.custody_account, "credit_in_account_currency": returned},
				],
				"Custody Return",
				_("Custody returned by {0} ({1})").format(doc.holder_name or doc.holder, doc.name),
			)
	doc.db_set(
		{
			"status": APPROVED,
			"approved_total": sum(flt(r.amount) for r in approved),
			"returned_amount": returned,
			"journal_entry": entry,
			"return_entry": return_entry,
			"confirmed_by": frappe.session.user,
		}
	)
	_close_tasks(doc)
	_refresh_custody(
		doc.custody,
		returned,
		closing=RETURNED if doc.leftover_action == RETURN else CARRIED,
		reopened=bool(rejected),
	)
	subject = _("Custody settlement approved: {0}").format(_money(sum(flt(r.amount) for r in approved)))
	if rejected:
		subject = _("{0}; {1} expense(s) rejected, see the reasons").format(subject, len(rejected))
		_task(
			doc,
			_("Fix the rejected custody expenses of {0}").format(doc.name),
			"\n".join(f"{r.work_date} {_money(r.amount)}: {r.reject_reason}" for r in rejected),
		)
	_notify(doc.holder, SETTLEMENT, doc.name, subject)
	return entry or return_entry


def _refresh_custody(name: str, returned: float, closing: str, reopened: bool) -> None:
	doc = frappe.get_doc(CUS, name)
	doc.reload()
	_totals(doc)
	status = SPENDING if reopened or any(r.status in (DRAFT, IN_SETTLEMENT) for r in doc.lines) else closing
	frappe.db.set_value(
		CUS,
		name,
		{
			"status": status,
			"spent_amount": doc.spent_amount,
			"approved_amount": doc.approved_amount,
			"returned_amount": flt(doc.returned_amount) + returned,
			"balance": _balance(doc.custody_account, doc.company),
		},
		update_modified=False,
	)


@frappe.whitelist(methods=["POST"])
def reject(name: str, reason: str) -> str:
	"""The whole settlement goes back to the holder with the reason; nothing is posted."""
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for the rejection."), frappe.MandatoryError)
	doc = _pending(name)
	# the expenses go back first: their link to this settlement would block its cancel
	_mark_lines(doc, LINE_REJECTED, reasons={r.line: reason for r in doc.lines})
	doc.flags.ignore_permissions = True
	doc.cancel()
	doc.db_set({"status": REJECTED, "reject_reason": reason})
	frappe.db.set_value(CUS, doc.custody, "status", SPENDING)
	_task(doc, _("Custody settlement rejected: {0}").format(reason), reason)
	_notify(
		doc.holder, SETTLEMENT, doc.name, _("Custody settlement {0} rejected: {1}").format(doc.name, reason)
	)
	return doc.name


def _task(doc, subject: str, description: str) -> None:
	frappe.get_doc(
		{
			"doctype": TASK,
			"subject": subject,
			"task_type": "Other",
			"assigned_to": doc.holder,
			"reference_doctype": CUS,
			"reference_name": doc.custody,
			"description": description,
		}
	).insert(ignore_permissions=True)


def _close_tasks(doc) -> None:
	for task in frappe.get_all(
		TASK, {"reference_doctype": SETTLEMENT, "reference_name": doc.name, "status": TASK_OPEN}, pluck="name"
	):
		frappe.db.set_value(
			TASK,
			task,
			{"status": TASK_DONE, "completed_by": frappe.session.user, "completed_on": now_datetime()},
		)


def _money(value) -> str:
	return frappe.format(flt(value), "Currency")


def _notify(user: str, doctype: str, name: str, subject: str) -> None:
	from frappe.desk.doctype.notification_log.notification_log import make_notification_logs

	if user:
		make_notification_logs(
			frappe._dict(
				{
					"type": "Alert",
					"document_type": doctype,
					"document_name": name,
					"subject": subject,
					"from_user": frappe.session.user,
				}
			),
			[user],
		)


# --- the confirmations centre (A1, SP-115) ---------------------------------------------------------


def pending_items(filters: dict) -> list[dict]:
	where = {"status": PENDING, "docstatus": 1}
	if filters.get("account"):
		where["custody_account"] = filters["account"]
	if filters.get("from_date"):
		where["period_to"] = (">=", filters["from_date"])
	if filters.get("to_date"):
		where["period_from"] = ("<=", filters["to_date"])
	rows = frappe.get_all(
		SETTLEMENT,
		where,
		["name", "holder", "holder_name", "period_to", "custody_account", "total", "leftover_action"],
		order_by="period_to asc, creation asc",
	)
	return [
		{
			"doctype": SETTLEMENT,
			"name": r.name,
			"kind": _(KIND),
			"recorder": r.holder,
			"date": r.period_to,
			"account": r.custody_account,
			"amount": flt(r.total),
			"photo": frappe.db.get_value(
				"SP Custody Settlement Line",
				{"parent": r.name, "receipt_photo": ("is", "set")},
				"receipt_photo",
			),
			"station": None,
			"party": _("{0} expenses").format(
				frappe.db.count("SP Custody Settlement Line", {"parent": r.name})
			),
		}
		for r in rows
	]


def preview(name: str) -> list[dict]:
	doc = frappe.get_doc(SETTLEMENT, name)
	rows = [r for r in doc.lines if r.decision != "Reject"]
	return [
		{
			"account": line["account"],
			"debit": flt(line.get("debit_in_account_currency")),
			"credit": flt(line.get("credit_in_account_currency")),
			"party": None,
			"cost_center": line.get("cost_center")
			or frappe.get_cached_value("Company", doc.company, "cost_center"),
			"project": line.get("project"),
			"station": frappe.db.get_value("Project", line.get("project"), "sp_station")
			if line.get("project")
			else None,
		}
		for line in _expense_lines(doc, rows)
	]


# --- A9 My custody --------------------------------------------------------------------------------


@frappe.whitelist()
def my_custody(holder: str | None = None) -> dict:
	"""The holder's balance, open custody with its expenses, and what the expense dialog offers."""
	user = frappe.session.user
	if holder and holder != user and not sees_all(user):
		frappe.throw(_("You see only your own custody."), frappe.PermissionError)
	holder = holder or user
	custodies = []
	for name in frappe.get_all(
		CUS,
		{"holder": holder, "docstatus": 1, "status": ("in", OPEN)},
		pluck="name",
		order_by="given_on desc",
	):
		doc = frappe.get_doc(CUS, name)
		custodies.append(
			{
				"name": doc.name,
				"given_on": doc.given_on,
				"amount": flt(doc.amount),
				"status": doc.status,
				"company": doc.company,
				"spent": flt(doc.spent_amount),
				"approved": flt(doc.approved_amount),
				"lines": [
					{
						"name": r.name,
						"work_date": r.work_date,
						"amount": flt(r.amount),
						"expense_type": r.expense_type,
						"type_label": frappe.db.get_value("SP List Value", r.expense_type, "value_ar")
						or r.expense_type,
						"where": _where(r),
						"status": r.status,
						"reject_reason": r.reject_reason,
						"receipt_photo": r.receipt_photo,
						"note": r.note,
					}
					for r in doc.lines
				],
			}
		)
	accounts = frappe.get_all(
		"Account", {"sp_account_kind": CUSTODY, "sp_holder": holder, "is_group": 0}, ["name", "company"]
	)
	companies = sorted({c["company"] for c in custodies})
	# what the expense dialog offers: a holder may not read stations or cost centers themselves
	stations = frappe.get_all(
		"SP Station",
		{"company": ("in", companies or [""]), "status": ("not in", ("Cancelled", "Financially closed"))},
		["name", "customer_name", "company"],
		order_by="name desc",
	)
	centers = frappe.get_all(
		"Cost Center",
		{"company": ("in", companies or [""]), "is_group": 0, "disabled": 0},
		["name", "cost_center_name", "company"],
		order_by="lft asc",
	)
	return {
		"holder": holder,
		"is_admin": is_admin(user),
		"balance": sum(_balance(a.name, a.company) for a in accounts),
		"stations": [
			{"value": r.name, "label": f"{r.name} · {r.customer_name or ''}", "company": r.company}
			for r in stations
		],
		"centers": [{"value": r.name, "label": r.cost_center_name, "company": r.company} for r in centers],
		# where leftover cash may be returned (a holder does not list official accounts, SP-26)
		"return_accounts": [
			{"value": r.name, "label": r.account_name, "company": r.company}
			for r in frappe.get_all(
				"Account",
				{
					"company": ("in", companies or [""]),
					"sp_account_kind": OFFICIAL,
					"is_group": 0,
					"disabled": 0,
				},
				["name", "account_name", "company"],
				order_by="account_name asc",
			)
		],
		"custodies": custodies,
		"settlements": frappe.get_all(
			SETTLEMENT,
			{"holder": holder, "docstatus": ("<", DocStatus.cancelled())},
			["name", "status", "total", "period_to", "leftover_action"],
			order_by="creation desc",
			limit=5,  # sp-allow-number: the last few
		),
	}


# --- who sees what --------------------------------------------------------------------------------


def query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	"""SP Custody and SP Custody Settlement: a holder sees only their own."""
	user = user or frappe.session.user
	if sees_all(user):
		return ""
	table = f"`tab{doctype or CUS}`"
	return f"{table}.`holder` = {frappe.db.escape(user)}"


def has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	return sees_all(user) or doc.get("holder") == user or doc.is_new()


def custody_query(user: str | None = None) -> str:
	"""permission_query_conditions for SP Custody."""
	return query_conditions(user, CUS)


def settlement_query(user: str | None = None) -> str:
	"""permission_query_conditions for SP Custody Settlement."""
	return query_conditions(user, SETTLEMENT)
