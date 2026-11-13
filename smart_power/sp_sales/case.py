"""Sales case rules (SP-46): one case per enquiry, with clear owners.

A case always has a follow-up owner (the case owner). The first owners are written to the
owner history when the case opens; later changes go through `reassign`, which needs a reason
and writes the history row (from, to, date, reason, by). Only the admin reassigns for now; the
hand-over between follow-up owners comes with SP-69.
`touch` marks the last action, for the case-inactivity rule (SP-71); calls (SP-67) and
quotes (SP-54) call it as they land.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from smart_power.sp_sales import quote_clock
from smart_power.sp_sales.quote_request import PAYMENT_LIST, clean_details

DOCTYPE = "SP Case"
QUOTE_REQUEST, DRAFT, WON, LOST = "Quote request", "Draft", "Won", "Lost"
SYSTEM_TYPE_LIST = "System Type"
LOST_REASON_LIST = "Lost Reason"
REASSIGN_ROLES = ("SP Admin", "System Manager")
# owner field → its label in the owner history
OWNER_FIELDS = {
	"requested_by": "Requested By",
	"quote_creator": "Quote Creator",
	"follow_up_owner": "Follow-up Owner",
}


def validate(doc) -> None:
	if not doc.follow_up_owner:
		frappe.throw(_("A case always has a follow-up owner."), frappe.MandatoryError)
	if doc.status == LOST and not doc.lost_reason:
		frappe.throw(_("A lost case needs a lost reason."), frappe.MandatoryError)
	_check_list(doc.lost_reason, LOST_REASON_LIST)
	for row in doc.system_types:
		_check_list(row.system_type, SYSTEM_TYPE_LIST)
	if doc.system_types:
		# only the first system type's request fields are kept (SP-47)
		system_type = doc.system_types[0].system_type
		if doc.request_details:
			doc.request_details = clean_details(system_type, doc.request_details)
	_check_list(doc.get("payment_method"), PAYMENT_LIST)
	take_request(doc)
	record_owner_changes(doc)
	quote_clock.on_validate(doc)
	if doc.is_new() or doc.has_value_changed("status"):
		doc.last_action_at = now_datetime()
		if doc.status == WON and not doc.won_on:
			doc.won_on = today()


def record_first_owners(doc) -> None:
	"""before_insert: one history row per owner the case opens with."""
	for fieldname, label in OWNER_FIELDS.items():
		if doc.get(fieldname):
			doc.append(
				"owner_history",
				{
					"role_kind": label,
					"to_user": doc.get(fieldname),
					"from_date": now_datetime(),
					"reason": _("Case opened"),
					"changed_by": frappe.session.user,
				},
			)


def take_request(doc) -> None:
	"""Whoever moves a quote request to Draft becomes its quote creator, unless one is set."""
	if doc.is_new() or doc.quote_creator or doc.status != DRAFT:
		return
	if doc.get_doc_before_save().status != QUOTE_REQUEST:
		return
	doc.quote_creator = frappe.session.user
	reasons = doc.flags.sp_owner_change_reasons or {}
	doc.flags.sp_owner_change_reasons = {**reasons, "quote_creator": _("Took the request")}


def record_owner_changes(doc) -> None:
	"""An owner changes only through reassign (with a reason); each change adds a history row."""
	if doc.is_new():
		return
	before = doc.get_doc_before_save()
	reasons = doc.flags.sp_owner_change_reasons or {}
	for fieldname, label in OWNER_FIELDS.items():
		old, new = before.get(fieldname), doc.get(fieldname)
		if old == new:
			continue
		if not reasons.get(fieldname):
			frappe.throw(
				_("To change the {0}, use Reassign and give a reason.").format(_(label)),
				title=_("Reassign"),
			)
		doc.append(
			"owner_history",
			{
				"role_kind": label,
				"from_user": old,
				"to_user": new,
				"from_date": now_datetime(),
				"reason": reasons[fieldname],
				"changed_by": frappe.session.user,
			},
		)


@frappe.whitelist(methods=["POST"])
def reassign(case: str, owner_field: str, to_user: str | None, reason: str) -> str:
	"""Give one of the case's owners to another user, with a reason (admin only for now)."""
	if owner_field not in OWNER_FIELDS:
		frappe.throw(_("Unknown owner {0}.").format(owner_field))
	if frappe.session.user != "Administrator" and not set(REASSIGN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin can reassign a case."), frappe.PermissionError)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is needed to reassign."), frappe.MandatoryError)
	doc = frappe.get_doc(DOCTYPE, case)
	doc.check_permission("write")
	if doc.get(owner_field) == (to_user or None):
		return doc.name
	doc.set(owner_field, to_user or None)
	doc.flags.sp_owner_change_reasons = {owner_field: reason}
	doc.save()
	return doc.name


def touch(case: str) -> None:
	"""Mark that something happened on the case now (a call, a quote, a status change)."""
	frappe.db.set_value(DOCTYPE, case, "last_action_at", now_datetime(), update_modified=False)


def _check_list(value: str | None, list_name: str) -> None:
	"""Link filters only steer the picker; a value from another list is refused on save."""
	if value and frappe.db.get_value("SP List Value", value, "list_name") != list_name:
		frappe.throw(_("{0} is not in the list {1}.").format(frappe.bold(value), _(list_name)))
