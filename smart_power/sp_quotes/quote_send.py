"""Send a quote version to the customer (SP-61).

    send_quote(quotation, print_format, channel) -> {file_url, log, warnings, mobile}

A draft version is submitted when it is first sent, so it never changes again (SP-54); a sent
version can be sent again. Every send prints a fresh PDF, keeps it as a private file on the quote
and writes a Quote Send Log row. The first send of the case moves it to "Sent to customer", which
stops the 24 h quote clock (SP-48); the requester and the follow-up owner are told, and the
follow-up owner gets a call task due after Follow-up Call After (days). A margin outside its
range is listed for the admin and never stops the send. The browser then shares the PDF to
WhatsApp (Web Share API on a phone; a download plus WhatsApp Web on a computer).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, now_datetime

from smart_power.rules import evaluate, record_warning
from smart_power.rules.sales import QUOTE_SEND_EVENT
from smart_power.sp_core.services.settings import get_value

CASE, LOG, TASK = "SP Case", "SP Quote Send Log", "SP Task"
CHANNELS = ("WhatsApp", "In person", "Other")
QUOTE_REQUEST, DRAFT_CASE, SENT_CASE = "Quote request", "Draft", "Sent to customer"
CLOSED = ("Won", "Lost")
CALL_TASK, REQUEST_TASK, TASK_OPEN = "Follow-up Call", "Quote Request", "Open"
FALLBACK_FORMAT = "SP Quotation"


def default_print_format() -> str:
	return get_value("default_quote_print_format") or FALLBACK_FORMAT


@frappe.whitelist()
def send_options(quotation: str) -> dict:
	"""What the Send dialog offers: the quote's print formats, the default one, the channels."""
	frappe.get_doc("Quotation", quotation).check_permission("read")
	formats = frappe.get_all(
		"Print Format", filters={"doc_type": "Quotation", "disabled": 0}, pluck="name", order_by="name asc"
	)
	from smart_power.sp_quotes.price_age import send_check

	return {
		"formats": formats,
		"default": default_print_format(),
		"channels": list(CHANNELS),
		# stale prices: a reason at Warn, no send at Block (SP-63)
		"price_age": send_check(frappe.get_doc("Quotation", quotation)),
	}


def _check_can_send(doc, case) -> None:
	from smart_power.sp_sales.quotation import _can_approve

	if not doc.get("sp_case"):
		frappe.throw(_("Only a quote linked to a case is sent from here."))
	if doc.docstatus.is_cancelled():
		frappe.throw(_("A cancelled quote cannot be sent."))
	if case.status in CLOSED:
		frappe.throw(
			_("Case {0} is {1}; its quotes are not sent any more.").format(case.name, _(case.status))
		)
	if not _can_approve(case):
		frappe.throw(
			_("Only the case's follow-up owner, its quote creator or the admin can send a quote."),
			frappe.PermissionError,
		)


@frappe.whitelist(methods=["POST"])
def send_quote(
	quotation: str, print_format: str | None = None, channel: str = "WhatsApp", reason: str | None = None
) -> dict:
	"""Send a version. `reason`: why it goes out with stale prices of a Warn category (SP-63)."""
	from smart_power.rules.sales import price_age_hit
	from smart_power.sp_quotes.price_age import check_before_send

	doc = frappe.get_doc("Quotation", quotation)
	case = frappe.get_doc(CASE, doc.sp_case) if doc.get("sp_case") else frappe._dict()
	_check_can_send(doc, case)
	check_before_send(doc, price_age_hit(doc), reason)
	if channel not in CHANNELS:
		frappe.throw(_("Unknown channel {0}.").format(frappe.bold(channel)))
	print_format = print_format or default_print_format()
	if frappe.db.get_value("Print Format", print_format, "doc_type") != "Quotation":
		frappe.throw(_("{0} is not a quote print format.").format(frappe.bold(print_format)))

	if doc.docstatus.is_draft():
		doc.check_permission("submit")
		doc.submit()  # the version is frozen: dated today, valid from today (SP-54)

	pdf = frappe.get_print("Quotation", doc.name, print_format, doc=doc, as_pdf=True)
	sends = frappe.db.count(LOG, {"quotation": doc.name})
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{doc.name}-{sends + 1}.pdf",
			"attached_to_doctype": "Quotation",
			"attached_to_name": doc.name,
			"is_private": 1,
			"content": pdf,
		}
	).insert(ignore_permissions=True)
	log = frappe.get_doc(
		{
			"doctype": LOG,
			"quotation": doc.name,
			"case": doc.sp_case,
			"version": doc.get("sp_version"),
			"option_label": doc.get("sp_option_label"),
			"channel": channel,
			"print_format": print_format,
			"sent_by": frappe.session.user,
			"sent_at": now_datetime(),
			"file": file.name,
			"file_url": file.file_url,
		}
	).insert(ignore_permissions=True)

	mark_case_sent(case)
	notify(doc, case)
	call_task(doc, case)
	warnings = check_margin(doc, reason)
	return {
		"file_url": file.file_url,
		"file_name": file.file_name,
		"log": log.name,
		"warnings": warnings,
		"mobile": case.get("mobile"),
	}


def mark_case_sent(case) -> None:
	"""The first send moves the case to "Sent to customer" through its workflow (the quote clock
	stops there); a request nobody took yet is taken by the sender first."""
	from frappe.model.workflow import apply_workflow

	if case.get("status") == QUOTE_REQUEST:
		case = apply_workflow(case, "Take Request")
	if case.get("status") == DRAFT_CASE:
		apply_workflow(case, "Send to Customer")
	# the quote request is answered: its open tasks are done (found in SP-67's browser check)
	for name in frappe.get_all(
		TASK,
		{
			"reference_doctype": CASE,
			"reference_name": case.name,
			"task_type": REQUEST_TASK,
			"status": TASK_OPEN,
		},
		pluck="name",
	):
		frappe.db.set_value(
			TASK,
			name,
			{"status": "Done", "completed_by": frappe.session.user, "completed_on": now_datetime()},
		)


def notify(doc, case) -> None:
	from smart_power.notify import send

	users = sorted({u for u in (case.get("requested_by"), case.get("follow_up_owner")) if u})
	if not users:
		return
	send(
		"quote_sent",
		users,
		# linked to the case: the requester may open the case but not the quote
		CASE,
		case.name,
		_("Quote {0} sent to {1}").format(doc.name, doc.get("customer_name") or doc.party_name),
		from_user=frappe.session.user,
	)


def call_task(doc, case) -> None:
	"""A call task for the follow-up owner, due after the follow-up delay; one open at a time."""
	owner = case.get("follow_up_owner")
	if not owner or frappe.db.exists(
		TASK,
		{"reference_doctype": CASE, "reference_name": case.name, "task_type": CALL_TASK, "status": TASK_OPEN},
	):
		return
	frappe.get_doc(
		{
			"doctype": TASK,
			"subject": _("Call {0} about quote {1}").format(
				doc.get("customer_name") or doc.party_name, doc.name
			),
			"task_type": CALL_TASK,
			"assigned_to": owner,
			"due_at": add_days(now_datetime(), cint(get_value("followup_delay_days", 0))),
			"reference_doctype": CASE,
			"reference_name": case.name,
		}
	).insert(ignore_permissions=True)


def check_margin(doc, reason: str | None = None) -> list[str]:
	"""A margin outside its range, or a stale price sent with a reason (SP-63), is listed for the
	admin; the send goes ahead."""
	from smart_power.rules.sales import PRICE_AGE_RULE

	messages = []
	for hit in evaluate(doc, QUOTE_SEND_EVENT):
		record_warning(doc, hit, reason if hit.spec.key == PRICE_AGE_RULE else None)
		messages.append(hit.finding.message)
	return messages


@frappe.whitelist()
def quote_history(case: str) -> list[dict]:
	"""Every quote version of a case (newest first) with every send and its PDF."""
	frappe.get_doc(CASE, case).check_permission("read")
	quotes = frappe.get_all(
		"Quotation",
		filters={"sp_case": case},
		fields=[
			"name",
			"sp_option_label",
			"sp_version",
			"sp_status",
			"sp_is_approved",
			"rounded_total",
			"grand_total",
			"currency",
			"transaction_date",
			"docstatus",
		],
		order_by="sp_version desc",
	)
	sends = frappe.get_all(
		LOG,
		filters={"case": case},
		fields=["quotation", "sent_at", "channel", "sent_by", "file_url"],
		order_by="sent_at desc",
	)
	by_quote = {}
	for send in sends:
		send.sent_by_name = frappe.utils.get_fullname(send.sent_by)
		by_quote.setdefault(send.quotation, []).append(send)
	for quote in quotes:
		quote.total = quote.rounded_total or quote.grand_total
		quote.sends = by_quote.get(quote.name, [])
	return quotes
