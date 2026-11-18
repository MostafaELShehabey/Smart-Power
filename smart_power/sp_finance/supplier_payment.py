"""Pay a supplier (SP-86): recorded by supplier accounts, confirmed by the admin like other money.

    Recorded (a draft Payment Entry, Pending) → Confirmed (submitted) / Rejected (stays a draft)

The payment goes out of an official account and may name a purchase order. On confirmation it is
set against the supplier's open invoices, the earliest due first: the named order's invoices only
when it names one. What is left over stays on the supplier's account as an advance. The order
shows what has been paid against it.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt, get_fullname, nowdate

from smart_power.notify import send
from smart_power.sp_core.inbox import HIGH, NORMAL, close_tasks, create_task
from smart_power.sp_core.services.settings import get_value
from smart_power.sp_stock.goods_receipt import _check_own_photo

ENTRY, INVOICE, ORDER = "Payment Entry", "Purchase Invoice", "Purchase Order"
PENDING, CONFIRMED, REJECTED = "Pending", "Confirmed", "Rejected"
PAY, SUPPLIER, OFFICIAL = "Pay", "Supplier", "Official"
CONFIRM_TASK, REJECT_TASK = "Supplier Payment to Confirm", "Other"
EVENT_REJECTED, EVENT_LARGE = "supplier_payment_rejected", "large_payment"
ADMIN_ROLE, ADMIN_ROLES = "SP Admin", ("SP Admin", "System Manager")
RECORDERS = ("SP Supplier Accounts", *ADMIN_ROLES)
KIND = "Supplier payment"


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def can_record(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(RECORDERS) & set(frappe.get_roles(user)))


def default_company() -> str | None:
	return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)


def official_accounts(company: str) -> list[str]:
	return frappe.get_all(
		"Account",
		{"company": company, "is_group": 0, "disabled": 0, "sp_account_kind": OFFICIAL},
		pluck="name",
		order_by="name asc",
	)


def open_invoices(supplier: str, company: str, purchase_order: str | None = None) -> list:
	"""The supplier's unpaid invoices, the earliest due first."""
	filters = {"supplier": supplier, "company": company, "docstatus": 1, "outstanding_amount": (">", 0)}
	if purchase_order:
		billed = frappe.get_all(
			"Purchase Invoice Item", {"purchase_order": purchase_order, "docstatus": 1}, pluck="parent"
		)
		filters["name"] = ("in", billed or [""])
	return frappe.get_all(
		INVOICE,
		filters,
		["name", "bill_no", "posting_date", "due_date", "grand_total", "outstanding_amount", "project"],
		order_by="due_date asc, posting_date asc, name asc",
	)


def _allocate(entry) -> None:
	"""Set the payment against the open invoices as they stand now."""
	entry.set("references", [])
	left = flt(entry.paid_amount)
	for invoice in open_invoices(entry.party, entry.company, entry.get("sp_purchase_order")):
		if left <= 0:
			break
		amount = min(left, flt(invoice.outstanding_amount))
		entry.append(
			"references",
			{
				"reference_doctype": INVOICE,
				"reference_name": invoice.name,
				"due_date": invoice.due_date,
				"total_amount": flt(invoice.grand_total),
				"outstanding_amount": flt(invoice.outstanding_amount),
				"allocated_amount": amount,
				"exchange_rate": 1,
			},
		)
		left = flt(left - amount)
	entry.set_amounts()


def _check(values: dict) -> None:
	if not can_record():
		frappe.throw(_("Only supplier accounts record supplier payments."), frappe.PermissionError)
	if flt(values.get("amount")) <= 0:
		frappe.throw(_("The amount must be above zero."))
	if values.get("account") not in official_accounts(values["company"]):
		frappe.throw(_("Pay from one of the official accounts."))
	if not cstr(values.get("reference_no")).strip():
		frappe.throw(_("Enter the payment reference."), frappe.MandatoryError)
	if not values.get("receipt_photo"):
		frappe.throw(_("Attach the payment receipt."), frappe.MandatoryError)
	_check_own_photo(values["receipt_photo"])
	order = values.get("purchase_order")
	if order and (frappe.db.get_value(ORDER, order, ["supplier", "docstatus"]) or (None, None)) != (
		values["supplier"],
		1,
	):
		frappe.throw(_("Purchase order {0} is not an open order of this supplier.").format(order))


@frappe.whitelist(methods=["POST"])
def record_payment(values: str | dict) -> str:
	"""values: supplier, amount, account, reference_no, receipt_photo, posting_date, purchase_order."""
	values = frappe.parse_json(values)
	values["company"] = values.get("company") or default_company()
	_check(values)
	user, day = frappe.session.user, values.get("posting_date") or nowdate()
	amount = flt(values["amount"])
	entry = frappe.get_doc(
		{
			"doctype": ENTRY,
			"payment_type": PAY,
			"party_type": SUPPLIER,
			"party": values["supplier"],
			"company": values["company"],
			"posting_date": day,
			"paid_from": values["account"],
			"paid_amount": amount,
			"received_amount": amount,
			"reference_no": cstr(values["reference_no"]).strip(),
			"reference_date": day,
			"remarks": _("Supplier payment to {0}").format(values["supplier"]),
			"sp_payment_status": PENDING,
			"sp_purchase_order": values.get("purchase_order"),
			"sp_receipt_photo": values["receipt_photo"],
			"sp_recorded_by": user,
		}
	)
	entry.flags.ignore_permissions = True  # checked above: the recorder may not read every account
	frappe.flags.sp_system_posting = True
	try:
		entry.setup_party_account_field()
		entry.set_missing_values()
		entry.insert()
	finally:
		frappe.flags.sp_system_posting = False
	_attach(entry)
	_confirm_task(entry)
	return entry.name


def _attach(entry) -> None:
	"""The receipt joins the payment, so the admin who confirms it can open it."""
	name = frappe.db.get_value(
		"File",
		{
			"file_url": entry.sp_receipt_photo,
			"owner": entry.sp_recorded_by,
			"attached_to_name": ("is", "not set"),
		},
	)
	if name:
		frappe.db.set_value(
			"File",
			name,
			{
				"attached_to_doctype": ENTRY,
				"attached_to_name": entry.name,
				"attached_to_field": "sp_receipt_photo",
			},
		)


def _confirm_task(entry) -> None:
	from smart_power.sp_sales.quote_request import _users_with

	threshold = flt(get_value("large_payment_threshold"))
	large = bool(threshold and flt(entry.paid_amount) > threshold)
	admins = _users_with(ADMIN_ROLE) or ["Administrator"]
	subject = _("Confirm payment of {0} to {1}").format(
		frappe.format(entry.paid_amount, "Currency"), entry.party_name or entry.party
	)
	create_task(
		CONFIRM_TASK,
		ENTRY,
		entry.name,
		admins,
		("⚠ " if large else "") + subject,
		amount=flt(entry.paid_amount),
		image=entry.sp_receipt_photo,
		priority=HIGH if large else NORMAL,
	)
	if large:
		send(EVENT_LARGE, admins, ENTRY, entry.name, _("Large payment: {0}").format(subject))


def _pending(name: str):
	if not is_admin():
		frappe.throw(_("Only the admin confirms or rejects a payment."), frappe.PermissionError)
	status = frappe.db.get_value(ENTRY, name, "sp_payment_status", for_update=True)
	if status != PENDING:
		frappe.throw(_("Payment {0} is not pending.").format(name))
	return frappe.get_doc(ENTRY, name)


@frappe.whitelist(methods=["POST"])
def confirm(name: str) -> str:
	"""The admin checked the money: it goes out and reduces what the supplier is owed."""
	entry = _pending(name)
	_allocate(entry)
	entry.sp_payment_status = CONFIRMED
	entry.flags.sp_confirming = True
	entry.flags.ignore_permissions = True
	frappe.flags.sp_system_posting = True  # the posting is the system's (SP-26)
	try:
		entry.submit()
	finally:
		frappe.flags.sp_system_posting = False
	close_tasks(ENTRY, entry.name, CONFIRM_TASK)
	return entry.name


@frappe.whitelist(methods=["POST"])
def reject(name: str, reason: str) -> str:
	"""Nothing is posted; the recorder gets the reason and can record the payment again."""
	reason = cstr(reason).strip()
	if not reason:
		frappe.throw(_("Give the reason for the rejection."), frappe.MandatoryError)
	entry = _pending(name)
	entry.db_set({"sp_payment_status": REJECTED, "sp_reject_reason": reason})
	close_tasks(ENTRY, entry.name, CONFIRM_TASK)
	subject = _("Payment to {0} was rejected: {1}").format(entry.party_name or entry.party, reason)
	create_task(REJECT_TASK, ENTRY, entry.name, entry.sp_recorded_by, subject, description=reason)
	send(EVENT_REJECTED, [entry.sp_recorded_by], ENTRY, entry.name, subject)
	return entry.name


def validate(doc, method=None) -> None:
	"""Payment Entry validate: a recorded payment stays as it was recorded."""
	if doc.get("sp_payment_status") and not doc.is_new() and not doc.flags.get("sp_confirming"):
		frappe.throw(_("A recorded payment cannot be changed."))


def before_submit(doc, method=None) -> None:
	"""Payment Entry before_submit: supplier money leaves only through the admin's confirmation."""
	if doc.flags.get("sp_confirming"):
		return
	if doc.get("sp_payment_status"):
		frappe.throw(_("The admin confirms this payment."), frappe.PermissionError)
	if doc.payment_type == PAY and doc.party_type == SUPPLIER and not is_admin():
		frappe.throw(_("Record supplier payments from the supplier ledger."), frappe.PermissionError)


def on_change(doc, method=None) -> None:
	"""Payment Entry on_submit and on_cancel: the order shows what has been paid against it."""
	order = doc.get("sp_purchase_order")
	if order:
		paid = frappe.get_all(ENTRY, {"sp_purchase_order": order, "docstatus": 1}, pluck="paid_amount")
		frappe.db.set_value(ORDER, order, "sp_paid_amount", sum(flt(p) for p in paid), update_modified=False)


# --- the confirmations centre (A1) -----------------------------------------------------------------


def pending_items(filters: dict) -> list[dict]:
	where = {"docstatus": 0, "sp_payment_status": PENDING}
	if filters.get("account"):
		where["paid_from"] = filters["account"]
	if filters.get("from_date") and filters.get("to_date"):
		where["posting_date"] = ("between", [filters["from_date"], filters["to_date"]])
	elif filters.get("from_date"):
		where["posting_date"] = (">=", filters["from_date"])
	elif filters.get("to_date"):
		where["posting_date"] = ("<=", filters["to_date"])
	rows = frappe.get_all(
		ENTRY,
		where,
		[
			"name",
			"sp_recorded_by",
			"posting_date",
			"paid_from",
			"paid_amount",
			"sp_receipt_photo",
			"party_name",
			"party",
		],
		order_by="posting_date asc, creation asc",
	)
	return [
		{
			"doctype": ENTRY,
			"name": r.name,
			"kind": _(KIND),
			"recorder": r.sp_recorded_by,
			"date": r.posting_date,
			"account": r.paid_from,
			"amount": flt(r.paid_amount),
			"photo": r.sp_receipt_photo,
			"station": None,
			"party": r.party_name or r.party,
		}
		for r in rows
	]


def preview(name: str) -> list[dict]:
	"""The lines the confirmation will post."""
	entry = frappe.get_doc(ENTRY, name)
	center = entry.get("cost_center") or frappe.get_cached_value("Company", entry.company, "cost_center")
	amount = flt(entry.paid_amount)
	base = {"cost_center": center, "project": None, "station": None}
	return [
		{"account": entry.paid_to, "debit": amount, "credit": 0, "party": entry.party, **base},
		{"account": entry.paid_from, "debit": 0, "credit": amount, "party": None, **base},
	]


@frappe.whitelist()
def payment_options(supplier: str) -> dict:
	"""What the Pay dialog offers."""
	if not can_record():
		frappe.throw(_("Only supplier accounts record supplier payments."), frappe.PermissionError)
	company = default_company()
	orders = frappe.get_all(
		ORDER,
		{
			"supplier": supplier,
			"docstatus": 1,
			"company": company,
			"status": ("not in", ("Closed", "Cancelled")),
		},
		["name", "transaction_date", "grand_total", "sp_paid_amount"],
		order_by="transaction_date desc",
	)
	return {
		"company": company,
		"accounts": official_accounts(company) if company else [],
		"orders": orders,
		"recorder": get_fullname(),
	}
