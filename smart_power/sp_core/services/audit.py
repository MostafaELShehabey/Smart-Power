"""Append-only logs: SP Audit Log and SP Edit Reason Log.

    audit(action, doctype, name, **details)   one SP Audit Log row, with the user's IP and browser
    @audited(action, doctype)                 audits a whitelisted action on a record once it
                                              succeeds (X13, SP-137): confirmations, rejections

Nobody edits or deletes an audit row, the admin included (prevent_change / prevent_delete).
"""

import functools
import inspect
import json

import frappe
from frappe import _

USER_AGENT_LENGTH = 500  # sp-allow-number: characters of the browser string kept


def _request() -> tuple[str | None, str | None]:
	ip = getattr(frappe.local, "request_ip", None)
	request = getattr(frappe.local, "request", None)
	agent = request.headers.get("User-Agent") if request is not None else None
	return ip, (agent or "")[:USER_AGENT_LENGTH] or None


def audit(action: str, reference_doctype: str | None = None, reference_name: str | None = None, **details):
	"""Write one SP Audit Log row. Details are stored as JSON."""
	ip, agent = _request()
	return frappe.get_doc(
		{
			"doctype": "SP Audit Log",
			"action": action,
			"user": frappe.session.user,
			"timestamp": frappe.utils.now_datetime(),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"details": json.dumps(details, default=str, ensure_ascii=False, indent=1) if details else None,
			"ip": ip,
			"user_agent": agent,
		}
	).insert(ignore_permissions=True)


def audited(action: str, doctype: str):
	"""Audit a record action once it has succeeded. Its first argument is the record's name; the
	other arguments given (a reason, an amount, the new owner) are the details."""

	def wrap(fn):
		signature = inspect.signature(fn)

		@functools.wraps(fn)
		def run(*args, **kwargs):
			result = fn(*args, **kwargs)
			given = signature.bind_partial(*args, **kwargs).arguments
			name = given.pop(next(iter(signature.parameters)), None)
			audit(action, doctype, name, **{k: v for k, v in given.items() if v not in (None, "")})
			return result

		return run

	return wrap


def log_edit(doc, fieldname: str, old_value, new_value, reason: str):
	"""Record an edit that needs a reason (decision 43: any number can be edited with a reason)."""
	if not (reason or "").strip():
		frappe.throw(_("A reason is required to change {0}.").format(_(doc.meta.get_label(fieldname))))
	return frappe.get_doc(
		{
			"doctype": "SP Edit Reason Log",
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"fieldname": fieldname,
			"old_value": str(old_value) if old_value is not None else None,
			"new_value": str(new_value) if new_value is not None else None,
			"reason": reason.strip(),
			"user": frappe.session.user,
		}
	).insert(ignore_permissions=True)


def prevent_change(doc, method=None):
	"""validate hook for append-only DocTypes."""
	if not doc.is_new():
		frappe.throw(_("{0} is append-only and cannot be edited.").format(_(doc.doctype)))


def prevent_delete(doc, method=None):
	"""on_trash hook for append-only DocTypes."""
	frappe.throw(_("{0} is append-only and cannot be deleted.").format(_(doc.doctype)))
