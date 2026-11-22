"""Transfer / deposit between money accounts (A4, SP-117).

    from account → to account, amount, date, reference, receipt photo

- A cash holder deposits from their own transit account (they are never offered someone else's);
  the admin may move money between any money accounts.
- A transfer is pending until the admin confirms it in A1 (SP-115); confirming posts Dr to /
  Cr from, which settles the transit balance and resets its days held (SP-116). Rejected: back to
  the recorder with the reason, nothing posted.
- The admin's own official → official transfer posts at once (no confirmation), and is audited.
- Moving more than a transit account holds is a warning, set in rule settings (transfer_over_balance).
- SH3 showroom deposit (SP-105): the showroom cashier deposits the shared showroom box (خزنة
  المعرض) into an official account. Until the admin confirms, the money is "deposit pending": out
  of the box's cash in hand (in_hand), not yet in the bank, and the books still show it in the box.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from smart_power.sp_core.inbox import close_tasks, create_task
from smart_power.sp_core.services.audit import audited
from smart_power.sp_finance.accounts import OFFICIAL, TRANSIT

TRANSFER, TASK = "SP Transfer", "SP Task"
DRAFT, PENDING, CONFIRMED, REJECTED = "Draft", "Pending", "Confirmed", "Rejected"
MONEY_KINDS = (OFFICIAL, TRANSIT)
CONFIRM_TASK = "Transfer to Confirm"  # in the admin's inbox (SP-39)
ADMIN_ROLE, ADMIN_ROLES = "SP Admin", ("SP Admin", "System Manager")
KIND = "Transfer / deposit"


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def _account(name: str) -> frappe._dict:
	return (
		frappe.db.get_value(
			"Account", name, ["sp_account_kind", "sp_holder", "company", "account_name"], as_dict=True
		)
		or frappe._dict()
	)


def showroom_box(company: str | None, user: str | None = None) -> str | None:
	"""The showroom box, when this user keeps it (the showroom cashier and the admin, SP-105)."""
	from smart_power.sp_finance.customer_payment import can_use_showroom_box, showroom_box_account

	return showroom_box_account(company) if can_use_showroom_box(user) else None


def sources(company: str, user: str | None = None) -> list[str]:
	"""The accounts this user may move money from: their own transit, and the showroom box for its
	cashier; the admin, any money account."""
	user = user or frappe.session.user
	filters = {"company": company, "is_group": 0, "disabled": 0}
	if is_admin(user):
		return frappe.get_all("Account", {**filters, "sp_account_kind": ("in", MONEY_KINDS)}, pluck="name")
	names = frappe.get_all(
		"Account", {**filters, "sp_account_kind": TRANSIT, "sp_holder": user}, pluck="name"
	)
	box = showroom_box(company, user)
	return [*names, box] if box and box not in names else names


def pending_out(account: str, exclude: str | None = None) -> float:
	"""Deposits out of the account still waiting for the admin: not yet posted (SP-105)."""
	filters = {"from_account": account, "docstatus": 1, "status": PENDING}
	if exclude:
		filters["name"] = ("!=", exclude)
	return flt(sum(flt(a) for a in frappe.get_all(TRANSFER, filters, pluck="amount")))


def in_hand(account: str, exclude: str | None = None) -> float:
	"""The cash still in the account: its balance less the deposits waiting for the admin."""
	from erpnext.accounts.utils import get_balance_on

	balance = flt(get_balance_on(account, ignore_account_permission=True))
	return balance - pending_out(account, exclude)


def destinations(company: str) -> list[str]:
	return frappe.get_all(
		"Account",
		{"company": company, "is_group": 0, "disabled": 0, "sp_account_kind": ("in", MONEY_KINDS)},
		pluck="name",
	)


# --- record -------------------------------------------------------------------------------------


def validate(doc) -> None:
	if doc.from_account == doc.to_account:
		frappe.throw(_("Choose two different accounts."))
	src, dst = _account(doc.from_account), _account(doc.to_account)
	if src.sp_account_kind not in MONEY_KINDS or dst.sp_account_kind not in MONEY_KINDS:
		frappe.throw(_("A transfer moves money between official and transit accounts only."))
	if src.company != dst.company:
		frappe.throw(_("Both accounts must belong to the same company."))
	doc.company = src.company
	if flt(doc.amount) <= 0:
		frappe.throw(_("The amount must be above zero."))
	if doc.is_new() or not doc.recorded_by:
		doc.recorded_by = frappe.session.user
		doc.entry_time = now_datetime()
	if not is_admin(doc.recorded_by) and doc.from_account not in sources(doc.company, doc.recorded_by):
		frappe.throw(_("You can move money only from your own transit account."), frappe.PermissionError)
	if (
		not is_admin(doc.recorded_by)
		and doc.from_account == showroom_box(doc.company, doc.recorded_by)
		and dst.sp_account_kind != OFFICIAL
	):
		frappe.throw(_("The showroom box is deposited into an official account."))
	if doc.docstatus.is_draft():
		doc.status = DRAFT
	if not doc.receipt_photo and not _posts_at_once(doc):
		frappe.throw(_("Attach the receipt photo."), frappe.MandatoryError)


def _posts_at_once(doc) -> bool:
	"""The admin's own official → official transfer needs no confirmation."""
	return (
		is_admin(doc.recorded_by)
		and _account(doc.from_account).sp_account_kind == OFFICIAL
		and _account(doc.to_account).sp_account_kind == OFFICIAL
	)


def on_submit(doc) -> None:
	if _posts_at_once(doc):
		from smart_power.sp_core.services.audit import audit

		_post(doc)
		audit(
			"Official transfer",
			doc.doctype,
			doc.name,
			from_account=doc.from_account,
			to_account=doc.to_account,
			amount=flt(doc.amount),
		)
		return
	doc.db_set("status", PENDING)
	from smart_power.sp_sales.quote_request import _users_with

	create_task(
		CONFIRM_TASK,
		TRANSFER,
		doc.name,
		_users_with(ADMIN_ROLE) or ["Administrator"],
		_("Confirm the transfer of {0} from {1}").format(
			frappe.format(doc.amount, "Currency"), _account(doc.from_account).account_name
		),
		amount=flt(doc.amount),
		image=doc.receipt_photo,
	)


def _build_entry(doc):
	return frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Bank Entry",
			"company": doc.company,
			"posting_date": doc.work_date,
			"cheque_no": doc.reference_no or doc.name,
			"cheque_date": doc.work_date,
			"user_remark": _("Transfer {0}").format(doc.name),
			"sp_posting_event": "Transfer",
			"sp_source_doctype": TRANSFER,
			"sp_source_name": doc.name,
			"accounts": [
				{"account": doc.to_account, "debit_in_account_currency": flt(doc.amount)},
				{"account": doc.from_account, "credit_in_account_currency": flt(doc.amount)},
			],
		}
	)


def _post(doc) -> str:
	je = _build_entry(doc)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	doc.db_set({"journal_entry": je.name, "status": CONFIRMED, "confirmed_by": frappe.session.user})
	return je.name


# --- confirm / reject (A1, SP-115) ----------------------------------------------------------------


def _pending(name: str):
	if not is_admin():
		frappe.throw(_("Only the admin confirms or rejects a transfer."), frappe.PermissionError)
	doc = frappe.get_doc(TRANSFER, name)
	if doc.status != PENDING:
		frappe.throw(_("Transfer {0} is {1}, not pending.").format(name, _(doc.status)))
	return doc


@frappe.whitelist(methods=["POST"])
@audited("Confirmed", "SP Transfer")  # X13 (SP-137)
def confirm(name: str) -> str:
	doc = _pending(name)
	entry = _post(doc)
	_close_tasks(doc)
	_notify(
		doc, [doc.recorded_by], _("Confirmed: transfer of {0}").format(frappe.format(doc.amount, "Currency"))
	)
	return entry


@frappe.whitelist(methods=["POST"])
@audited("Rejected", "SP Transfer")  # X13 (SP-137)
def reject(name: str, reason: str) -> str:
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for the rejection."), frappe.MandatoryError)
	doc = _pending(name)
	doc.flags.sp_rejecting = True
	doc.cancel()
	doc.db_set({"status": REJECTED, "reject_reason": reason})
	_close_tasks(doc)
	subject = _("Rejected: transfer of {0}: {1}").format(frappe.format(doc.amount, "Currency"), reason)
	_notify(doc, [doc.recorded_by], subject)
	if doc.recorded_by:
		frappe.get_doc(
			{
				"doctype": TASK,
				"subject": subject,
				"task_type": "Other",
				"assigned_to": doc.recorded_by,
				"reference_doctype": TRANSFER,
				"reference_name": doc.name,
				"description": reason,
			}
		).insert(ignore_permissions=True)
	return doc.name


def on_cancel(doc) -> None:
	"""A rejection posts nothing; a confirmed transfer's entry is cancelled with it (SP-113 hook)."""
	if doc.status == PENDING:
		doc.db_set("status", REJECTED)
	_close_tasks(doc)


def _close_tasks(doc) -> None:
	close_tasks(TRANSFER, doc.name)


def _notify(doc, users, subject: str) -> None:
	from smart_power.notify import send

	users = sorted({u for u in users if u})
	if users:
		send(
			"transfer_decided",
			users,
			TRANSFER,
			doc.name,
			subject,
			from_user=frappe.session.user,
		)


# --- the confirmations centre source (SP-115) -----------------------------------------------------


def pending_items(filters: dict) -> list[dict]:
	where = {"status": PENDING, "docstatus": 1}
	if filters.get("account"):
		where["to_account"] = filters["account"]
	if filters.get("from_date") and filters.get("to_date"):
		where["work_date"] = ("between", [filters["from_date"], filters["to_date"]])
	elif filters.get("from_date"):
		where["work_date"] = (">=", filters["from_date"])
	elif filters.get("to_date"):
		where["work_date"] = ("<=", filters["to_date"])
	rows = frappe.get_all(
		TRANSFER,
		filters=where,
		fields=["name", "recorded_by", "work_date", "from_account", "to_account", "amount", "receipt_photo"],
		order_by="work_date asc, creation asc",
	)
	return [
		{
			"doctype": TRANSFER,
			"name": r.name,
			"kind": _(KIND),
			"recorder": r.recorded_by,
			"date": r.work_date,
			"account": r.to_account,
			"amount": flt(r.amount),
			"photo": r.receipt_photo,
			"station": None,
			# the page reads "<amount> from <party>": the source account is the party
			"party": frappe.db.get_value("Account", r.from_account, "account_name") or r.from_account,
		}
		for r in rows
	]


def preview(name: str) -> list[dict]:
	doc = frappe.get_doc(TRANSFER, name)
	center = frappe.get_cached_value("Company", doc.company, "cost_center")
	return [
		{
			"account": r.account,
			"debit": flt(r.debit_in_account_currency),
			"credit": flt(r.credit_in_account_currency),
			"party": None,
			"cost_center": center,
			"project": None,
			"station": None,
		}
		for r in _build_entry(doc).accounts
	]


# --- the A4 dialog -------------------------------------------------------------------------------


def _company() -> str | None:
	from smart_power.sp_core.services.company import COMPANY_SETTINGS

	return frappe.db.get_single_value(COMPANY_SETTINGS, "company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)


@frappe.whitelist()
def transfer_options(company: str | None = None) -> dict:
	"""What the Transfer dialog offers this user: the sources (with the cash in hand, less the
	deposits waiting for the admin) and the destinations. The cashier deposits the showroom box
	into an official account only."""
	company = company or _company()
	names = sources(company)
	box = None if is_admin() else showroom_box(company)
	rows = frappe.get_all(
		"Account",
		filters={"name": ("in", sorted(set(names) | set(destinations(company))) or [""])},
		fields=["name", "account_name", "sp_account_kind"],
		order_by="sp_account_kind asc, account_name asc",
	)
	label = {r.name: r.account_name for r in rows}
	return {
		"company": company,
		"is_admin": is_admin(),
		"sources": [
			{
				"value": n,
				"label": label.get(n, n),
				"balance": in_hand(n),
				"official_only": n == box,
			}
			for n in names
		],
		"destinations": [{"value": r.name, "label": r.account_name, "kind": r.sp_account_kind} for r in rows],
	}


@frappe.whitelist(methods=["POST"])
def record_transfer(values: str | dict) -> str:
	"""Record and submit a transfer from the dialog: pending, or posted for the admin's own."""
	values = frappe.parse_json(values)
	allowed = ("from_account", "to_account", "amount", "work_date", "reference_no", "receipt_photo")
	doc = frappe.get_doc({"doctype": TRANSFER, **{k: values.get(k) for k in allowed if values.get(k)}})
	doc.insert()
	doc.submit()
	return doc.name
