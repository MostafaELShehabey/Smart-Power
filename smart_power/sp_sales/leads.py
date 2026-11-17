"""Marketing leads (SP-51): مها's own leads, each a future quote request counted in its campaign.

ERPNext's Lead with Smart Power fields: the mobile (one lead or customer per mobile, as C3), the
source (the Lead Source list), the campaign (SP-52), the follow-up owner the request will go to
(the follow-up lead by default) and the case it became.

    validate(doc)                  mobile, duplicates, defaults
    query_conditions / has_permission
                                   a user sees the leads they made, own or follow up; the admin
                                   and the follow-up lead see all (no filter can widen it)
    convert_options(lead)          what C3 opens with
    link_request(lead, case)       C3 saved: the lead points to its case and is converted
    waiting_count(user)            the user's leads still without a request after 24 h
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, get_link_to_form, now_datetime

from smart_power.sp_sales.customer import (
	find_by_mobile,
	is_erpnext_test_data,
	is_valid_mobile,
	normalize_mobile,
)

LEAD = "Lead"
SEES_ALL = ("SP Admin", "System Manager", "SP Followup All")
FOLLOWUP_LEAD_ROLE = "SP Followup All"
CONVERTED = "Converted"
WAIT_HOURS = 24  # sp-allow-number: the story's 24 hours without a request


def validate(doc, method=None) -> None:
	if is_erpnext_test_data():
		return  # ERPNext's own test leads have no mobile
	mobile = normalize_mobile(doc.get("sp_mobile") or doc.get("mobile_no"))
	if not mobile:
		frappe.throw(_("Mobile is required: it is how a returning customer is found."), frappe.MandatoryError)
	if not is_valid_mobile(mobile):
		frappe.throw(_("{0} is not a valid Egyptian mobile.").format(frappe.bold(mobile)))
	doc.sp_mobile = mobile
	doc.mobile_no = doc.mobile_no or mobile
	duplicate = duplicate_of(mobile, exclude=doc.name if not doc.is_new() else None)
	if duplicate:
		doctype, name = duplicate
		frappe.throw(
			_("This mobile is already {0} {1}.").format(_(doctype), get_link_to_form(doctype, name)),
			frappe.DuplicateEntryError,
		)
	if not doc.get("sp_source") and doc.get("sp_campaign"):
		doc.sp_source = frappe.db.get_value("SP Campaign", doc.sp_campaign, "channel")
	doc.sp_follow_up_owner = doc.get("sp_follow_up_owner") or followup_lead()
	doc.lead_owner = doc.get("lead_owner") or frappe.session.user


def duplicate_of(mobile: str, exclude: str | None = None) -> tuple[str, str] | None:
	"""("Customer", name) or ("Lead", name) already holding this mobile."""
	customer = find_by_mobile(mobile)
	if customer:
		return "Customer", customer
	filters = {"sp_mobile": mobile}
	if exclude:
		filters["name"] = ("!=", exclude)
	lead = frappe.db.get_value(LEAD, filters)
	return ("Lead", lead) if lead else None


def followup_lead() -> str | None:
	"""كاميليا: the first enabled holder of SP Followup All (assumption #5)."""
	users = frappe.get_all("Has Role", {"role": FOLLOWUP_LEAD_ROLE, "parenttype": "User"}, pluck="parent")
	enabled = frappe.get_all(
		"User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name", order_by="creation asc"
	)
	return enabled[0] if enabled else None


# --- who sees which lead ------------------------------------------------------------------------


def _sees_all(user: str) -> bool:
	return user == "Administrator" or bool(set(SEES_ALL) & set(frappe.get_roles(user)))


def query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _sees_all(user):
		return ""
	u = frappe.db.escape(user)
	return f"(`tabLead`.owner = {u} or `tabLead`.lead_owner = {u} or `tabLead`.sp_follow_up_owner = {u})"


def has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if doc.is_new() or _sees_all(user):
		return True
	return user in (doc.owner, doc.get("lead_owner"), doc.get("sp_follow_up_owner"))


# --- a lead becomes a quote request (C3) ---------------------------------------------------------


@frappe.whitelist()
def convert_options(lead: str) -> dict:
	"""What C3 opens with: the mobile, the name, marketing as the channel, the source, the campaign
	and the follow-up owner; saving links the request back to the lead."""
	doc = frappe.get_doc(LEAD, lead)
	doc.check_permission("read")
	if doc.get("sp_case"):
		frappe.throw(_("This lead is already request {0}.").format(get_link_to_form("SP Case", doc.sp_case)))
	options = {
		"lead": doc.name,
		"mobile": doc.sp_mobile,
		"customer_name": doc.lead_name or doc.company_name,
		"channel": "Marketing",
		"source": doc.get("sp_source"),
		"campaign": doc.get("sp_campaign"),
		"follow_up_owner": doc.get("sp_follow_up_owner"),
	}
	# route options travel in the URL: an empty one would arrive as the text "null"
	return {k: v for k, v in options.items() if v}


def link_request(lead: str | None, case) -> None:
	"""C3 saved a request from a lead: the lead points to it and is converted."""
	if not lead:
		return
	doc = frappe.get_doc(LEAD, lead)
	doc.check_permission("read")
	frappe.db.set_value(LEAD, lead, {"sp_case": case.name, "status": CONVERTED})
	if doc.get("sp_campaign") and not case.get("campaign"):
		case.db_set("campaign", doc.sp_campaign)


def waiting_filters(user: str) -> dict:
	return {
		"owner": user,
		"sp_case": ("is", "not set"),
		"creation": ("<", add_to_date(now_datetime(), hours=-WAIT_HOURS)),
	}


def waiting_count(user: str) -> int:
	return frappe.db.count(LEAD, waiting_filters(user))
