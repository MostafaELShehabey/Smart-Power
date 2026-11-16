"""Edit with reason (SP-44, component 1): change a saved number with a reason.

    edit_field(doctype, name, fieldname, value, reason)

A field is editable this way only when it is registered in EDITABLE, with the roles that may
change it and, where the value has consequences (a posted entry, a station's money), the
module function that applies the change. Every change lands in the document's History (a
Version: old → new), in the Edit Reason Log with its reason, and in the admin's review
(RV2, Edits with reason).
"""

import frappe
from frappe import _
from frappe.utils import cstr

ADMIN = ("SP Admin", "System Manager")

# (doctype, fieldname) → {"roles": who may change it, "apply": the module's change (optional)}
EDITABLE = {
	("SP Customer Payment", "amount"): {
		"roles": ADMIN,
		"apply": "smart_power.sp_finance.customer_payment.change_amount",
	},
}


@frappe.whitelist()
def editable_fields(doctype: str, name: str) -> list[str]:
	"""For the form: the fields this user may change with a reason."""
	frappe.has_permission(doctype, "read", doc=name, throw=True)
	return [f for (dt, f), spec in EDITABLE.items() if dt == doctype and _may(spec)]


def _may(spec: dict) -> bool:
	user = frappe.session.user
	return user == "Administrator" or bool(set(spec["roles"]) & set(frappe.get_roles(user)))


@frappe.whitelist(methods=["POST"])
def edit_field(doctype: str, name: str, fieldname: str, value: str | float, reason: str) -> dict:
	"""Change one registered field with a reason; returns {old, new}."""
	from smart_power.sp_core.review_centre import raise_item
	from smart_power.sp_core.services.audit import log_edit

	spec = EDITABLE.get((doctype, fieldname))
	if not spec:
		frappe.throw(_("{0} cannot be changed this way.").format(fieldname))
	if not _may(spec):
		frappe.throw(_("You may not change this value."), frappe.PermissionError)
	if not (reason or "").strip():
		frappe.throw(_("A reason is required."), title=_("Reason needed"))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	df = doc.meta.get_field(fieldname)
	new = frappe.utils.cast(df.fieldtype, value)
	old = doc.get(fieldname)
	if cstr(old) == cstr(new):
		frappe.throw(_("The value is the same."))
	if spec.get("apply"):
		frappe.get_attr(spec["apply"])(doc, new)
	else:
		doc.db_set(fieldname, new, update_modified=True)
	frappe.get_doc(
		{
			"doctype": "Version",
			"ref_doctype": doctype,
			"docname": name,
			"data": frappe.as_json({"changed": [[fieldname, old, new]], "sp_reason": reason.strip()}),
		}
	).insert(ignore_permissions=True)
	log_edit(doc, fieldname, old, new, reason)
	label = _(doc.meta.get_label(fieldname))
	raise_item(
		"Edit",
		doc,
		_("{0}: {1} {2} → {3}. {4}").format(
			name, label, frappe.format(old, df), frappe.format(new, df), reason.strip()
		),
		amount=new if df.fieldtype in ("Currency", "Float") else None,
	)
	return {"old": old, "new": new}


def boot(bootinfo) -> None:
	"""boot_session: the doctypes whose forms get edit-with-reason buttons."""
	bootinfo.sp_editable = sorted({dt for dt, _f in EDITABLE})
