"""Record a customer payment (A2, SP-114): the collection owner or the showroom cashier records it
with its receipt, and the admin confirms it against the bank or the cash.

    Draft → Pending (submitted by the recorder) → Confirmed (posted) / Rejected (back with a reason)

- The receiving account is an official account (Bank Misr, InstaPay, the Post, Vodafone Cash) or
  the recorder's own transit account (cash in hand); accounts are flagged on the Account itself
  (Money Kind: Official / Transit + holder, SP-26). The Treasury (SP-116) lists them and
  counts the days a transit balance is held.
- A receipt photo is needed, except for cash into the recorder's own transit account.
- Pending money shows on the station as pending; Paid counts confirmed payments only.
- On confirm: a Payment Entry (Receive, the customer, into the receiving account, the station's
  project, allocated to the contract as an advance), or for money the customer paid straight to a
  third party a Journal Entry (Dr the supplier or expense / Cr the customer's receivable). A
  deposit (on a case) is a deposit Payment Entry, which runs the deposit automation (SP-175).
- On reject: no entry; the payment is cancelled with the reason, the recorder is told and can
  amend it.
- The admin has a "Payment to Confirm" task with the photo; a payment above Large Payment
  (Smart Power Settings) is highlighted and alerted.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from smart_power.sp_core.inbox import HIGH, NORMAL, close_tasks, create_task
from smart_power.sp_finance.accounts import mode_for_method

PAYMENT, STATION, CASE, TASK = "SP Customer Payment", "SP Station", "SP Case", "SP Task"
DRAFT, PENDING, CONFIRMED, REJECTED = "Draft", "Pending", "Confirmed", "Rejected"
OFFICIAL, TRANSIT = "Official", "Transit"
CASH, THIRD_PARTY = "Payment Method-CASH", "Payment Method-THIRD_PARTY"
CONFIRM_TASK = "Payment to Confirm"  # in the admin's inbox (SP-39)
ADMIN_ROLE, ADMIN_ROLES = "SP Admin", ("SP Admin", "System Manager")


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def receiving_accounts(company: str, user: str | None = None) -> list[str]:
	"""The accounts this user may record money into: the official ones and their own transit."""
	user = user or frappe.session.user
	return frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "disabled": 0, "sp_account_kind": OFFICIAL},
		pluck="name",
	) + frappe.get_all(
		"Account",
		filters={
			"company": company,
			"is_group": 0,
			"disabled": 0,
			"sp_account_kind": TRANSIT,
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
		"Account", doc.receiving_account, ["sp_account_kind", "sp_holder", "company"]
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
	# a collected postal cheque is its own proof (SP-118)
	if not doc.receipt_photo and not doc.get("cheque") and not (own_transit and doc.method == CASH):
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
	create_task(
		CONFIRM_TASK,
		PAYMENT,
		doc.name,
		admins,
		("⚠ " if large else "") + subject,
		amount=flt(doc.amount),
		image=doc.receipt_photo,
		priority=HIGH if large else NORMAL,
	)
	if large:
		_notify(doc, admins, _("Large payment: {0}").format(subject), "large_payment")


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
	return post_confirmed(_pending(name))


def post_confirmed(doc) -> str:
	"""Post a pending payment. The admin's Confirm comes here; so does a collected postal cheque
	when Smart Power Settings confirm those at once (SP-118)."""
	if doc.status != PENDING:
		frappe.throw(_("Payment {0} is {1}, not pending.").format(doc.name, _(doc.status)))
	# the posting is the system's: it reaches the official accounts whoever triggered it (SP-26)
	frappe.flags.sp_system_posting = True
	try:
		if doc.method == THIRD_PARTY:
			entry = _third_party_entry(doc)
			doc.db_set("journal_entry", entry)
		else:
			entry = _payment_entry(doc)
			doc.db_set("payment_entry", entry)
	finally:
		frappe.flags.sp_system_posting = False
	doc.db_set({"status": CONFIRMED, "confirmed_by": frappe.session.user})
	_close_tasks(doc)
	_refresh(doc)
	owner = frappe.db.get_value(STATION, doc.station, "collection_owner") if doc.station else None
	_notify(
		doc,
		[doc.recorded_by, owner],
		_("Confirmed: {0} from {1}").format(frappe.format(doc.amount, "Currency"), doc.customer_name),
		"payment_confirmed",
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
	subject = _("Rejected: {0} from {1}: {2}").format(
		frappe.format(doc.amount, "Currency"), doc.customer_name, reason
	)
	_notify(doc, [doc.recorded_by], subject, "receipt_rejected")
	if doc.recorded_by:
		# the recorder fixes it: amend the payment with what the admin asked (SP-115)
		frappe.get_doc(
			{
				"doctype": TASK,
				"subject": subject,
				"task_type": "Other",
				"assigned_to": doc.recorded_by,
				"reference_doctype": PAYMENT,
				"reference_name": doc.name,
				"description": reason,
			}
		).insert(ignore_permissions=True)
	return doc.name


def on_cancel(doc) -> None:
	"""A rejection posts nothing; cancelling a confirmed payment reverses its entry."""
	if doc.flags.sp_rejecting:
		return
	for doctype, name in (("Payment Entry", doc.payment_entry), ("Journal Entry", doc.journal_entry)):
		if name and frappe.db.get_value(doctype, name, "docstatus") == 1:
			entry = frappe.get_doc(doctype, name)
			entry.flags.ignore_permissions = True
			entry.flags.sp_allow_cancel = True  # the payment's own entry (SP-119)
			entry.cancel()
	doc.db_set("status", REJECTED if doc.status == PENDING else doc.status)
	_close_tasks(doc)
	_refresh(doc)


def _receivable(company: str) -> str:
	return frappe.get_cached_value("Company", company, "default_receivable_account")


def _payment_entry(doc) -> str:
	pe = _build_payment_entry(doc)
	pe.flags.ignore_permissions = True
	pe.insert()
	pe.submit()  # a deposit runs SP-175 here
	return pe.name


def _build_payment_entry(doc):
	"""The Payment Entry a confirmation posts, unsaved (the confirmations centre previews it)."""
	from smart_power.sp_finance.centers import station_center

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
			# a station's money posts to the Projects center (SP-27)
			"cost_center": station_center(doc.company) if so else None,
			"remarks": _("Customer payment {0}").format(doc.name),
			"mode_of_payment": mode_for_method(doc.method),
			"sp_is_deposit": doc.is_deposit,
			"sp_case": doc.case if doc.is_deposit else None,
		}
	)
	pe.setup_party_account_field()
	pe.set_missing_values()
	if so and so.sales_order and not doc.is_deposit:
		_allocate_to_contract(pe, so.sales_order)
	return pe


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
	je = _build_third_party_entry(doc)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je.name


def _build_third_party_entry(doc):
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
	return je


# --- helpers ----------------------------------------------------------------------------------------


def _close_tasks(doc) -> None:
	close_tasks(PAYMENT, doc.name)


def _refresh(doc) -> None:
	if doc.station:
		from smart_power.sp_stations.money import refresh

		refresh(doc.station)


def _notify(doc, users, subject: str, event: str) -> None:
	from smart_power.notify import send

	users = sorted({u for u in users if u})
	if users:
		send(
			event,
			users,
			PAYMENT,
			doc.name,
			subject,
			from_user=frappe.session.user,
		)


# --- the A2 dialog ----------------------------------------------------------------------------------

RECORDER_ROLES = (
	"SP Collection Officer",
	"SP Showroom Cashier",
	"SP Customer Followup",
	"SP Followup All",
	"SP Project Manager",
	*ADMIN_ROLES,
)


def can_record(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(RECORDER_ROLES) & set(frappe.get_roles(user)))


@frappe.whitelist()
def payment_options(station: str | None = None, case: str | None = None) -> dict:
	"""What the Record Payment dialog offers this user: the accounts and the amount still due."""
	if station:
		doc = frappe.get_doc(STATION, station)
		doc.check_permission("read")
		company, due = doc.company, flt(doc.remaining_amount) - flt(doc.pending_amount)
	elif case:
		frappe.get_doc(CASE, case).check_permission("read")
		quote = frappe.db.get_value(CASE, case, "accepted_quotation")
		company = frappe.db.get_value("Quotation", quote, "company") if quote else None
		due = 0.0
	else:
		frappe.throw(_("Choose the station or the case."))
	company = company or frappe.defaults.get_user_default("Company")
	return {
		"can_record": can_record(),
		"company": company,
		"accounts": [
			{
				"value": a.name,
				"label": _("{0} (yours)").format(a.account_name)
				if a.sp_account_kind == TRANSIT
				else a.account_name,
			}
			for a in frappe.get_all(
				"Account",
				filters={"name": ("in", receiving_accounts(company) or [""])},
				fields=["name", "account_name", "sp_account_kind"],
				order_by="sp_account_kind asc, account_name asc",
			)
		],
		"due": max(due, 0.0),
	}


@frappe.whitelist(methods=["POST"])
def record_payment(values: str | dict) -> str:
	"""Record and submit a customer payment from the dialog; it is then pending confirmation."""
	if not can_record():
		frappe.throw(_("You do not record customer payments."), frappe.PermissionError)
	values = frappe.parse_json(values)
	allowed = (
		"station", "case", "is_deposit", "amount", "work_date", "method", "receiving_account",
		"reference_no", "receipt_photo", "channel", "third_party_type", "third_party",
	)  # fmt: skip
	doc = frappe.get_doc({"doctype": PAYMENT, **{k: values.get(k) for k in allowed if values.get(k)}})
	doc.insert()
	doc.submit()
	return doc.name


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def account_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | None = None
):
	"""The Receiving Account picker: the official accounts and the user's own transit."""
	company = (filters or {}).get("company") or frappe.defaults.get_user_default("Company")
	names = receiving_accounts(company)
	txt = (txt or "").lower()
	rows = [(n,) for n in names if txt in n.lower()]
	return rows[int(start) : int(start) + int(page_len)]


# --- the confirmations centre (SP-115) ---------------------------------------------------------------

KIND = "Customer payment"


def pending_items(filters: dict) -> list[dict]:
	"""This source's pending items for A1, in the centre's shape."""
	where = {"status": PENDING, "docstatus": 1}
	if filters.get("account"):
		where["receiving_account"] = filters["account"]
	if filters.get("from_date"):
		where["work_date"] = (">=", filters["from_date"])
	if filters.get("to_date"):
		where["work_date"] = (
			("between", [filters["from_date"], filters["to_date"]])
			if filters.get("from_date")
			else ("<=", filters["to_date"])
		)
	rows = frappe.get_all(
		PAYMENT,
		filters=where,
		fields=[
			"name", "recorded_by", "work_date", "receiving_account", "third_party", "amount",
			"receipt_photo", "station", "case", "customer_name", "is_deposit", "channel",
		],
		order_by="work_date asc, creation asc",
	)  # fmt: skip
	return [
		{
			"doctype": PAYMENT,
			"name": r.name,
			"kind": _("Deposit") if r.is_deposit else _(KIND),
			"recorder": r.recorded_by,
			"date": r.work_date,
			"account": r.receiving_account or r.third_party,
			"amount": flt(r.amount),
			"photo": r.receipt_photo,
			"station": r.station or r.case,
			"party": r.customer_name,
		}
		for r in rows
	]


def preview(name: str) -> list[dict]:
	"""The exact lines the confirmation will post: Dr / Cr, party, center and station."""
	doc = frappe.get_doc(PAYMENT, name)
	if doc.method == THIRD_PARTY:
		entry = _build_third_party_entry(doc)
		return [
			{
				"account": r.account,
				"debit": flt(r.debit_in_account_currency),
				"credit": flt(r.credit_in_account_currency),
				"party": r.get("party"),
				"cost_center": r.get("cost_center")
				or frappe.get_cached_value("Company", doc.company, "cost_center"),
				"project": r.get("project"),
				"station": doc.station if r.get("project") else None,
			}
			for r in entry.accounts
		]
	pe = _build_payment_entry(doc)
	center = pe.get("cost_center") or frappe.get_cached_value("Company", doc.company, "cost_center")
	return [
		{"account": pe.paid_to, "debit": flt(pe.paid_amount), "credit": 0, "party": None, "cost_center": center, "project": pe.project, "station": doc.station},
		{"account": pe.paid_from, "debit": 0, "credit": flt(pe.paid_amount), "party": pe.party, "cost_center": center, "project": pe.project, "station": doc.station},
	]  # fmt: skip


def change_amount(doc, amount) -> None:
	"""Edit with reason (SP-44): a pending payment just takes the new amount; a confirmed one has
	its entry reversed (cancelled) and posted again for the new amount."""
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("The amount must be above zero."))
	if doc.status not in (PENDING, CONFIRMED):
		frappe.throw(_("Payment {0} is {1}; its amount cannot change.").format(doc.name, _(doc.status)))
	if doc.status == PENDING:
		doc.db_set("amount", amount, update_modified=True)
		for task in frappe.get_all(
			"SP Task",
			{"reference_doctype": PAYMENT, "reference_name": doc.name, "status": "Open"},
			pluck="name",
		):
			frappe.db.set_value("SP Task", task, "amount", amount)
		_refresh(doc)
		return
	for field, doctype in (("payment_entry", "Payment Entry"), ("journal_entry", "Journal Entry")):
		name = doc.get(field)
		if name and frappe.db.get_value(doctype, name, "docstatus") == 1:
			doc.db_set(field, None)  # the payment stays submitted: its link must not stop the cancel
			entry = frappe.get_doc(doctype, name)
			entry.flags.ignore_permissions = True
			entry.flags.sp_allow_cancel = True  # the payment's own entry (SP-119)
			entry.cancel()
	doc.db_set("amount", amount, update_modified=True)
	doc.reload()
	frappe.flags.sp_system_posting = True
	try:
		if doc.method == THIRD_PARTY:
			doc.db_set("journal_entry", _third_party_entry(doc))
		else:
			doc.db_set("payment_entry", _payment_entry(doc))
	finally:
		frappe.flags.sp_system_posting = False
	_refresh(doc)
