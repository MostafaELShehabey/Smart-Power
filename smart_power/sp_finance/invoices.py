"""Internal invoices (SP-125; decisions 2, 7, 61, 72): one yearly series, printed on request.

Tax invoices stay outside the system. Every internal Sales Invoice is numbered SINV-.YYYY.-.####:
the station final invoices (SP-80) and the ad-hoc ones (a company customer, a bank request), so
the series is Sales Invoice's default. The showroom receipts keep their own SHR- series (SP-102).

- Cancelling one needs a reason, and only the admin cancels (owner, 2026-11-22): cancel_invoice.
  The number stays used (ERPNext never reuses a name); the reason goes to the Review centre.
- Printing is on request, by the admin or the accountant (owner): print_invoice logs who printed,
  when, and for whom (a bank or the customer); print_log reads it back.

ERPNext numbers .YYYY. by the day the invoice is created (unless Global Defaults says to use the
posting date), so each year starts again at 0001.
"""

import frappe
from frappe import _

from smart_power.sp_core.services.audit import audit
from smart_power.sp_stations.close import INVOICE_SERIES

SI = "Sales Invoice"
ADMIN_ROLES = ("SP Admin", "System Manager")
PRINT_ROLES = ("SP Accountant", *ADMIN_ROLES)
FOR_KINDS = ("Bank", "Customer")
PRINTED, CANCELLED = "Invoice printed", "Invoice cancelled"
CATEGORY = "Invoice Cancellation"


def _has(roles) -> bool:
	return frappe.session.user == "Administrator" or bool(set(roles) & set(frappe.get_roles()))


def is_internal(doc) -> bool:
	return doc.doctype == SI and (doc.get("naming_series") == INVOICE_SERIES or doc.name.startswith("SINV-"))


def ensure_default_series() -> None:
	"""A new Sales Invoice takes the internal series unless it asks for another (SHR-)."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	from smart_power.sp_stations.close import ensure_invoice_series

	ensure_invoice_series()
	if frappe.get_meta(SI).get_field("naming_series").default != INVOICE_SERIES:
		make_property_setter(
			SI, "naming_series", "default", INVOICE_SERIES, "Text", validate_fields_for_doctype=False
		)


def _internal(name: str):
	doc = frappe.get_doc(SI, name)
	if not is_internal(doc):
		frappe.throw(_("{0} is not an internal invoice.").format(frappe.bold(name)))
	return doc


# --- cancelling, with a reason ----------------------------------------------------------------------


def before_cancel(doc, method=None) -> None:
	"""Sales Invoice before_cancel: an internal invoice is cancelled only with its reason."""
	if is_internal(doc) and not doc.flags.sp_cancel_reason:
		frappe.throw(
			_("Cancel an internal invoice with Cancel with Reason; the admin gives the reason."),
			title=_("Reason needed"),
		)


@frappe.whitelist(methods=["POST"])
def cancel_invoice(name: str, reason: str) -> str:
	"""The admin cancels an internal invoice with a reason; its number stays used."""
	from smart_power.sp_core.review_centre import raise_item

	if not _has(ADMIN_ROLES):
		frappe.throw(_("Only the admin cancels an internal invoice."), frappe.PermissionError)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for cancelling."), frappe.MandatoryError)
	doc = _internal(name)
	if doc.docstatus != 1:
		frappe.throw(_("Invoice {0} is not submitted.").format(name))
	doc.flags.sp_cancel_reason = reason
	doc.flags.ignore_permissions = True
	doc.cancel()
	doc.add_comment("Info", _("Cancelled: {0}").format(reason))
	raise_item(
		CATEGORY,
		doc,
		_("Invoice {0} ({1}) cancelled: {2}").format(doc.name, doc.customer_name, reason),
		amount=doc.grand_total,
	)
	audit(CANCELLED, SI, doc.name, reason=reason, amount=doc.grand_total)
	return doc.name


# --- printing on request ----------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def print_invoice(name: str, for_kind: str, for_whom: str | None = None) -> str:
	"""Log who prints the invoice, when, and for whom; the page then opens the print."""
	if not _has(PRINT_ROLES):
		frappe.throw(
			_("Only the admin or the accountant prints an internal invoice."), frappe.PermissionError
		)
	if for_kind not in FOR_KINDS:
		frappe.throw(_("Print it for a bank or for the customer."))
	doc = _internal(name)
	if doc.docstatus != 1:
		frappe.throw(_("Invoice {0} is not submitted.").format(name))
	whom = (for_whom or "").strip() or (doc.customer_name if for_kind == "Customer" else "")
	if not whom:
		frappe.throw(_("Name the bank the invoice is printed for."), frappe.MandatoryError)
	audit(PRINTED, SI, doc.name, printed_for=for_kind, whom=whom)
	return doc.name


@frappe.whitelist()
def print_log(name: str) -> list[dict]:
	"""Who printed the invoice, when, and for whom."""
	import json

	if not _has(PRINT_ROLES):
		frappe.throw(_("Only the admin or the accountant reads the print log."), frappe.PermissionError)
	rows = frappe.get_all(
		"SP Audit Log",
		{"reference_doctype": SI, "reference_name": name, "action": PRINTED},
		["user", "timestamp", "details"],
		order_by="timestamp desc",
	)
	out = []
	for r in rows:
		details = json.loads(r.details or "{}")
		out.append(
			{
				"user": r.user,
				"at": r.timestamp,
				"for_kind": details.get("printed_for"),
				"whom": details.get("whom"),
			}
		)
	return out
