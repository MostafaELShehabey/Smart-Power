"""Append-only logs: SP Audit Log and SP Edit Reason Log."""

import json

import frappe
from frappe import _


def audit(action: str, reference_doctype: str | None = None, reference_name: str | None = None, **details):
	"""Write one SP Audit Log row. Details are stored as JSON."""
	return frappe.get_doc(
		{
			"doctype": "SP Audit Log",
			"action": action,
			"user": frappe.session.user,
			"timestamp": frappe.utils.now_datetime(),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"details": json.dumps(details, default=str, ensure_ascii=False, indent=1) if details else None,
		}
	).insert(ignore_permissions=True)


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
