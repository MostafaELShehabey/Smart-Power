"""The review centre queue (SP Review Item)."""

import frappe


def open_review_item(
	*,
	category: str,
	reference_doctype: str,
	reference_name: str,
	summary: str,
	amount: float | None = None,
	highlight: bool = False,
	rule: str | None = None,
	reason: str | None = None,
):
	"""Open a review item, or refresh the one already open for the same rule and document.

	Links are not validated: a rule fires while its document is still being inserted, and the
	item is written in the same transaction, so both are kept or rolled back together.
	"""
	filters = {
		"category": category,
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
		"status": "Open",
	}
	if rule:
		filters["rule"] = rule
	name = frappe.db.get_value("SP Review Item", filters)
	values = {
		"summary": summary,
		"amount": amount,
		"highlight": int(bool(highlight)),
		"reason": reason,
		"raised_by": frappe.session.user,
	}
	if name:
		doc = frappe.get_doc("SP Review Item", name)
		doc.update(values)
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)
		return doc
	return frappe.get_doc({"doctype": "SP Review Item", **filters, "rule": rule, **values}).insert(
		ignore_permissions=True, ignore_links=True
	)
