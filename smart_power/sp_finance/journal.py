"""Journal (A6) and manual entry (A6b) (SP-119).

- Every Journal Entry carries its source (sp_source_doctype / sp_source_name, set by SP-113's
  posting service and the money documents); the A6 list shows and filters it.
- A posted entry is never edited or cancelled by hand: it is reversed. Reverse makes a new
  reversing entry linked to the original (ERPNext's reversal_of). An entry made by a document (a
  payment, a transfer …) is reversed by cancelling that document, so the two never disagree;
  only those code paths may cancel an entry (flags.sp_allow_cancel).
- An entry without a source is a manual entry (A6b): it is flagged (sp_is_manual) and listed in
  the review centre's "Manual entries". The form shows a live balanced check (SP-119 JS).
"""

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.utils import flt, today

JE = "Journal Entry"


def allow_cancel(entry) -> None:
	"""Code that cancels an entry because its source was cancelled says so first."""
	entry.flags.sp_allow_cancel = True
	entry.flags.ignore_permissions = True


def before_cancel(doc, method=None) -> None:
	"""Journal Entry before_cancel: a posted entry is reversed, never cancelled (for every user)."""
	if doc.flags.sp_allow_cancel:
		return
	if doc.get("sp_source_doctype") and doc.get("sp_source_name"):
		frappe.throw(
			_("Entry {0} comes from {1} {2}: cancel or correct that document instead.").format(
				doc.name, _(doc.sp_source_doctype), doc.sp_source_name
			),
			title=_("Reverse, never cancel"),
		)
	frappe.throw(
		_("A posted entry is never cancelled. Use Reverse to post a reversing entry."),
		title=_("Reverse, never cancel"),
	)


def has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""No one cancels or amends a posted entry (Administrator is stopped by before_cancel)."""
	if ptype in ("cancel", "amend") and doc.docstatus == 1:
		return False
	return True


def on_submit(doc, method=None) -> None:
	"""An entry without a source document is a manual entry: flagged and listed for the admin."""
	from smart_power.sp_core.review_centre import raise_item

	if doc.get("sp_source_doctype"):
		return
	doc.db_set("sp_is_manual", 1)
	summary = (
		_("Reversal {0} of {1}").format(doc.name, doc.reversal_of)
		if doc.get("reversal_of")
		else _("Manual entry {0}: {1}").format(doc.name, doc.user_remark or doc.title or "")
	)
	raise_item("Manual Entry", doc, summary, amount=flt(doc.total_debit))


@frappe.whitelist(methods=["POST"])
def reverse(name: str) -> str:
	"""A6 Reverse: a draft reversing entry of a manual entry, linked to it (submit to post)."""
	from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry

	source = frappe.get_doc(JE, name)
	source.check_permission("read")
	if source.docstatus != 1:
		frappe.throw(_("Only a posted entry is reversed."))
	if source.get("sp_source_doctype") and source.get("sp_source_name"):
		frappe.throw(
			_("Entry {0} comes from {1} {2}: cancel or correct that document instead.").format(
				name, _(source.sp_source_doctype), source.sp_source_name
			)
		)
	existing = frappe.db.get_value(JE, {"reversal_of": name, "docstatus": ("<", DocStatus.cancelled())})
	if existing:
		return existing
	reversal = make_reverse_journal_entry(name)
	reversal.posting_date = reversal.posting_date or today()  # the reversal posts today
	reversal.user_remark = _("Reversal of {0}").format(name)
	reversal.insert()
	return reversal.name
