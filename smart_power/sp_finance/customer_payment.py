"""Record a customer payment (A2, SP-114): the collection owner or the showroom cashier records it
with its receipt, and the admin confirms it against the bank or the cash.

    Draft → Pending (submitted by the recorder) → Confirmed (posted) / Rejected (back with a reason)

- The receiving account is an official account (Bank Misr, InstaPay, the Post, Vodafone Cash) or
  the recorder's own transit account (cash in hand); accounts are flagged on the Account itself
  (Receives Customer Money: Official / Transit + holder). The Treasury (SP-116) lists them and
  counts the days a transit balance is held.
- A receipt photo is needed, except for cash into the recorder's own transit account.
- Pending money shows on the station as pending; Paid counts confirmed payments only.
- On confirm: a Payment Entry (Receive, the customer, into the receiving account, the station's
  project, allocated to the contract as an advance), or for money the customer paid straight to a
  third party a Journal Entry (Dr the supplier or expense / Cr the customer's receivable). A
  deposit (on a case) is a deposit Payment Entry, which runs the deposit automation (SP-175).
- On reject: no entry; the payment is cancelled with the reason, the recorder is told and can
  amend it.
- The admin has a "Receipt to Confirm" task with the photo; a payment above Large Payment
  (Smart Power Settings) is highlighted and alerted.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

PAYMENT, STATION, CASE, TASK = "SP Customer Payment", "SP Station", "SP Case", "SP Task"
DRAFT, PENDING, CONFIRMED, REJECTED = "Draft", "Pending", "Confirmed", "Rejected"
OFFICIAL, TRANSIT = "Official", "Transit"
CASH, THIRD_PARTY = "Payment Method-CASH", "Payment Method-THIRD_PARTY"
CONFIRM_TASK, TASK_OPEN, TASK_DONE = "Receipt to Confirm", "Open", "Done"
ADMIN_ROLE, ADMIN_ROLES = "SP Admin", ("SP Admin", "System Manager")


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def receiving_accounts(company: str, user: str | None = None) -> list[str]:
	"""The accounts this user may record money into: the official ones and their own transit."""
	user = user or frappe.session.user
	return frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "disabled": 0, "sp_receiving_kind": OFFICIAL},
		pluck="name",
	) + frappe.get_all(
		"Account",
		filters={
			"company": company,
			"is_group": 0,
			"disabled": 0,
			"sp_receiving_kind": TRANSIT,
			"sp_holder": user,
		},
		pluck="name",
	)


# --- record -------------------------------------------------------------------------------------


def validate(doc) -> None:
	if doc.station:
		doc.customer, doc.company = frappe.db.get_value(STATION, doc.station, ["customer", "company"])
		doc.case = doc.case or frappe.db.get_value(STATION, doc.station, "case")
	elif doc.case:
		doc.customer, quote = frappe.db.get_value(CASE, doc.case, ["customer", "accepted_quotation"])
		doc.company = doc.company or (frappe.db.get_value("Quotation", quote, "company") if quote else None)
	else:
		frappe.throw(_("Choose the station, or the case for a deposit before the station exists."))
	if not doc.station and not doc.is_deposit:
		frappe.throw(_("Only a deposit is recorded on a case; other payments go on the station."))
	doc.company = doc.company or frappe.defaults.get_user_default("Company")
	doc.customer_name = frappe.db.get_value("Customer", doc.customer, "customer_name")
	if flt(doc.amount) <= 0:
		frappe.throw(_("The amount must be above zero."))
	if doc.is_new() or not doc.recorded_by:
		doc.recorded_by = frappe.session.user
		doc.entry_time = now_datetime()
	if doc.docstatus.is_draft():
		doc.status = DRAFT
	if doc.method == THIRD_PARTY:
		if not (doc.third_party_type and doc.third_party):
			frappe.throw(_("Name the third party the customer paid."))
		if doc.is_deposit:
			frappe.throw(_("A deposit is received by Smart Power, not paid to a third party."))
		doc.receiving_account = None
	else:
		doc.third_party_type = doc.third_party = None
		_check_receiving_account(doc)


def _check_receiving_account(doc) -> None:
	if not doc.receiving_account:
		frappe.throw(_("Choose the account that received the money."), frappe.MandatoryError)
	kind, holder, company = frappe.db.get_value(
		"Account", doc.receiving_account, ["sp_receiving_kind", "sp_holder", "company"]
	)
	if company != doc.company:
		frappe.throw(_("Account {0} is not an account of {1}.").format(doc.receiving_account, doc.company))
	own_transit = kind == TRANSIT and holder == doc.recorded_by
	if kind != OFFICIAL and not own_transit:
		frappe.throw(
			_("{0} is neither an official account nor your own transit account.").format(
				frappe.bold(doc.receiving_account)
			)
		)
	if not doc.receipt_photo and not (own_transit and doc.method == CASH):
		frappe.throw(_("Attach the receipt photo."), frappe.MandatoryError)


def on_submit(doc) -> None:
	"""Recorded: pending the admin's confirmation."""
	doc.db_set("status", PENDING)
	_confirm_task(doc)
	_refresh(doc)


def _confirm_task(doc) -> None:
	from smart_power.sp_core.services.settings import get_value
	from smart_power.sp_sales.quote_request import _users_with

	threshold = flt(get_value("large_payment_threshold"))
	large = bool(threshold and flt(doc.amount) > threshold)
	admins = _users_with(ADMIN_ROLE) or ["Administrator"]
	subject = _("Confirm {0} from {1} ({2})").format(
		frappe.format(doc.amount, "Currency"), doc.customer_name, doc.station or doc.case
	)
	for admin in admins:
		frappe.get_doc(
			{
				"doctype": TASK,
				"subject": ("⚠ " if large else "") + subject,
				"task_type": CONFIRM_TASK,
				"assigned_to": admin,
				"reference_doctype": PAYMENT,
				"reference_name": doc.name,
				"description": doc.receipt_photo or "",
			}
		).insert(ignore_permissions=True)
	if large:
		_notify(doc, admins, _("Large payment: {0}").format(subject))


# --- confirm / reject ------------------------------------------------------------------------------


def _pending(name: str):
	if not is_admin():
		frappe.throw(_("Only the admin confirms or rejects a payment."), frappe.PermissionError)
	doc = frappe.get_doc(PAYMENT, name)
	if doc.status != PENDING:
		frappe.throw(_("Payment {0} is {1}, not pending.").format(name, _(doc.status)))
	return doc


@frappe.whitelist(methods=["POST"])
def confirm(name: str) -> str:
	"""The admin checked the money: post it. Returns the entry's name."""
	doc = _pending(name)
	if doc.method == THIRD_PARTY:
		entry = _third_party_entry(doc)
		doc.db_set("journal_entry", entry)
	else:
		entry = _payment_entry(doc)
		doc.db_set("payment_entry", entry)
	doc.db_set({"status": CONFIRMED, "confirmed_by": frappe.session.user})
	_close_tasks(doc)
	_refresh(doc)
	owner = frappe.db.get_value(STATION, doc.station, "collection_owner") if doc.station else None
	_notify(
		doc,
		[doc.recorded_by, owner],
		_("Confirmed: {0} from {1}").format(frappe.format(doc.amount, "Currency"), doc.customer_name),
	)
	return entry


@frappe.whitelist(methods=["POST"])
def reject(name: str, reason: str) -> str:
	"""Back to the recorder with the reason; nothing is posted. The recorder can amend it."""
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for the rejection."), frappe.MandatoryError)
	doc = _pending(name)
	doc.flags.sp_rejecting = True
	doc.reject_reason = reason
	doc.cancel()
	doc.db_set({"status": REJECTED, "reject_reason": reason})
	_close_tasks(doc)
	_refresh(doc)
	_notify(
		doc,
		[doc.recorded_by],
		_("Rejected: {0} from {1}: {2}").format(
			frappe.format(doc.amount, "Currency"), doc.customer_name, reason
		),
	)
	return doc.name


def on_cancel(doc) -> None:
	"""A rejection posts nothing; cancelling a confirmed payment reverses its entry."""
	if doc.flags.sp_rejecting:
		return
	for doctype, name in (("Payment Entry", doc.payment_entry), ("Journal Entry", doc.journal_entry)):
		if name and frappe.db.get_value(doctype, name, "docstatus") == 1:
			entry = frappe.get_doc(doctype, name)
			entry.flags.ignore_permissions = True
			entry.cancel()
	doc.db_set("status", REJECTED if doc.status == PENDING else doc.status)
	_close_tasks(doc)
	_refresh(doc)


def _receivable(company: str) -> str:
	return frappe.get_cached_value("Company", company, "default_receivable_account")


def _payment_entry(doc) -> str:
	so = (
		frappe.db.get_value(STATION, doc.station, ["sales_order", "project"], as_dict=True)
		if doc.station
		else None
	)
	pe = frappe.get_doc(
		{
			"doctype": "Payment Entry",
			"payment_type": "Receive",
			"company": doc.company,
			"posting_date": doc.work_date,
			"party_type": "Customer",
			"party": doc.customer,
			"paid_from": _receivable(doc.company),
			"paid_to": doc.receiving_account,
			"paid_amount": flt(doc.amount),
			"received_amount": flt(doc.amount),
			"reference_no": doc.reference_no or doc.name,
			"reference_date": doc.work_date,
			"project": so.project if so else None,
			"remarks": _("Customer payment {0}").format(doc.name),
			"sp_is_deposit": doc.is_deposit,
			"sp_case": doc.case if doc.is_deposit else None,
		}
	)
	pe.setup_party_account_field()
	pe.set_missing_values()
	if so and so.sales_order and not doc.is_deposit:
		_allocate_to_contract(pe, so.sales_order)
	pe.flags.ignore_permissions = True
	pe.insert()
	pe.submit()  # a deposit runs SP-175 here
	return pe.name


def _allocate_to_contract(pe, sales_order: str) -> None:
	"""The payment is the contract's advance (the schedule is paid oldest instalment first)."""
	so = frappe.db.get_value(
		"Sales Order",
		sales_order,
		["docstatus", "rounded_total", "grand_total", "advance_paid"],
		as_dict=True,
	)
	if not so or so.docstatus != 1:
		return
	total = flt(so.rounded_total or so.grand_total)
	outstanding = total - flt(so.advance_paid)
	if outstanding <= 0:
		return
	pe.append(
		"references",
		{
			"reference_doctype": "Sales Order",
			"reference_name": sales_order,
			"total_amount": total,
			"outstanding_amount": outstanding,
			"allocated_amount": min(flt(pe.paid_amount), outstanding),
		},
	)


def _third_party_entry(doc) -> str:
	"""Money the customer paid straight to a supplier (or an expense): Dr them / Cr the customer."""
	project = frappe.db.get_value(STATION, doc.station, "project") if doc.station else None
	if doc.third_party_type == "Supplier":
		debit = {
			"account": frappe.get_cached_value("Company", doc.company, "default_payable_account"),
			"party_type": "Supplier",
			"party": doc.third_party,
		}
	else:
		debit = {"account": doc.third_party}
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": doc.company,
			"posting_date": doc.work_date,
			"user_remark": _("Customer {0} paid {1} directly ({2})").format(
				doc.customer_name, doc.third_party, doc.name
			),
			"sp_source_doctype": PAYMENT,
			"sp_source_name": doc.name,
			"accounts": [
				{**debit, "debit_in_account_currency": flt(doc.amount), "project": project},
				{
					"account": _receivable(doc.company),
					"party_type": "Customer",
					"party": doc.customer,
					"credit_in_account_currency": flt(doc.amount),
					"project": project,
				},
			],
		}
	)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name


# --- helpers ----------------------------------------------------------------------------------------


def _close_tasks(doc) -> None:
	for name in frappe.get_all(
		TASK,
		{"reference_doctype": PAYMENT, "reference_name": doc.name, "status": TASK_OPEN},
		pluck="name",
	):
		frappe.db.set_value(
			TASK,
			name,
			{"status": TASK_DONE, "completed_by": frappe.session.user, "completed_on": now_datetime()},
		)


def _refresh(doc) -> None:
	if doc.station:
		from smart_power.sp_stations.money import refresh

		refresh(doc.station)


def _notify(doc, users, subject: str) -> None:
	from frappe.desk.doctype.notification_log.notification_log import make_notification_logs

	users = sorted({u for u in users if u})
	if users:
		make_notification_logs(
			frappe._dict(
				{
					"type": "Alert",
					"document_type": PAYMENT,
					"document_name": doc.name,
					"subject": subject,
					"from_user": frappe.session.user,
				}
			),
			users,
		)
