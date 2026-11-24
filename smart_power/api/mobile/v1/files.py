"""files.upload (SP-148): a photo or a voice note, attached to a record the user may edit."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail


@endpoint(methods=("POST",))
def upload(doctype: str | None = None, name: str | None = None, fieldname: str | None = None) -> dict:
	"""Multipart `file`; the phone compresses it first. Private, and attached only to a record the
	user may write."""
	uploaded = frappe.request.files.get("file") if frappe.request else None
	if not uploaded:
		fail("VALIDATION", _("Send the file in the field 'file'."))
	if doctype and name:
		frappe.has_permission(doctype, "write", doc=name, throw=True)
	doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": uploaded.filename,
			"content": uploaded.stream.read(),
			"is_private": 1,
			"attached_to_doctype": doctype,
			"attached_to_name": name,
			"attached_to_field": fieldname,
		}
	).insert()
	return {"name": doc.name, "file_url": doc.file_url}
