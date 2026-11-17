"""Marketing campaigns (SP-52, MK1 / MK2): spend and results per campaign.

    refresh(campaign)        recount one campaign: spend, leads, quotes, won, contracted value
    funnel(doc)              leads → quotes → won → contracted value, for the record's chart
    refresh_active()         the nightly job: every active campaign

The funnel comes from what carries the campaign:

    leads             Leads with the campaign (SP-51 makes them)
    quotes            the campaign's cases that got a sent quote
    won               the campaign's cases that are won
    contracted value  the approved quote of each won case
    spend             approved custody expenses with the campaign (ERD 7.4)

A change to any of them recounts its campaign at once (doc events); the nightly job catches the
rest. A marketing agent sees the campaigns she owns; the admin and the follow-up lead see all.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

CAMPAIGN = "SP Campaign"
CASE = "SP Case"
ACTIVE, CLOSED = "Active", "Closed"
WON = "Won"
SUBMITTED = 1
LINE_APPROVED = "Approved"
SEES_ALL = ("SP Admin", "System Manager", "SP Followup All")


def validate(doc) -> None:
	doc.owner_user = doc.owner_user or frappe.session.user
	if doc.end_date and getdate(doc.end_date) < getdate(doc.start_date):
		frappe.throw(_("The campaign cannot end before it starts."))
	if frappe.db.get_value("SP List Value", doc.channel, "list_name") != "Lead Source":
		frappe.throw(_("Choose the campaign's channel."))


# --- the results ----------------------------------------------------------------------------------


def counts(campaign: str) -> dict:
	cases = frappe.get_all(CASE, {"campaign": campaign}, ["name", "status", "accepted_quotation"])
	names = [c.name for c in cases] or [""]
	quoted = set(
		frappe.get_all("Quotation", {"sp_case": ("in", names), "docstatus": SUBMITTED}, pluck="sp_case")
	)
	won = [c for c in cases if c.status == WON]
	accepted = [c.accepted_quotation for c in won if c.accepted_quotation] or [""]
	contracted = sum(
		flt(v) for v in frappe.get_all("Quotation", {"name": ("in", accepted)}, pluck="grand_total")
	)
	spend = sum(
		flt(v)
		for v in frappe.get_all(
			"SP Custody Line", {"campaign": campaign, "status": LINE_APPROVED}, pluck="amount"
		)
	)
	leads = frappe.db.count("Lead", {"sp_campaign": campaign}) if _lead_has_campaign() else 0
	return {
		"spend_total": spend,
		"lead_count": leads,
		"quote_count": len(quoted),
		"won_count": len(won),
		"contracted_value": contracted,
	}


def _lead_has_campaign() -> bool:
	return frappe.db.has_column("Lead", "sp_campaign")


def refresh(campaign: str | None) -> dict | None:
	"""Recount one campaign and store its results."""
	if not campaign or not frappe.db.exists(CAMPAIGN, campaign):
		return None
	values = counts(campaign)
	frappe.db.set_value(
		CAMPAIGN, campaign, {**values, "stats_updated_on": now_datetime()}, update_modified=False
	)
	return values


def refresh_active() -> None:
	"""Nightly: every active campaign (what changed without passing through a doc event)."""
	for name in frappe.get_all(CAMPAIGN, {"status": ACTIVE}, pluck="name"):
		refresh(name)


def funnel(doc) -> list[dict]:
	return [
		{"label": _("Leads"), "value": doc.lead_count or 0},
		{"label": _("Quotes"), "value": doc.quote_count or 0},
		{"label": _("Won"), "value": doc.won_count or 0},
	]


# --- what changes the results (doc events) --------------------------------------------------------


def on_case_change(doc, method=None) -> None:
	"""SP Case on_update: its campaign (and the one it left) recount when status or campaign change."""
	before = doc.get_doc_before_save()
	old = before.get("campaign") if before else None
	if (
		before
		and old == doc.get("campaign")
		and before.status == doc.status
		and (before.get("accepted_quotation") == doc.get("accepted_quotation"))
	):
		return
	for campaign in {old, doc.get("campaign")}:
		refresh(campaign)


def on_quote_change(doc, method=None) -> None:
	"""Quotation on_submit / on_cancel: the case's campaign recounts its quotes."""
	if doc.get("sp_case"):
		refresh(frappe.db.get_value(CASE, doc.sp_case, "campaign"))


def on_lead_change(doc, method=None) -> None:
	"""Lead after_insert / on_update / on_trash: its campaign recounts its leads."""
	before = doc.get_doc_before_save() if method == "on_update" else None
	for campaign in {doc.get("sp_campaign"), before.get("sp_campaign") if before else None}:
		refresh(campaign)


def on_custody_lines(campaigns: set) -> None:
	"""Custody lines approved or rejected: their campaigns recount the spend."""
	for campaign in campaigns:
		refresh(campaign)


# --- who sees which campaign ----------------------------------------------------------------------


def _sees_all(user: str) -> bool:
	return user == "Administrator" or bool(set(SEES_ALL) & set(frappe.get_roles(user)))


def query_conditions(user: str | None = None) -> str:
	"""A marketing agent sees the campaigns she owns; the admin and the follow-up lead see all."""
	user = user or frappe.session.user
	if _sees_all(user):
		return ""
	u = frappe.db.escape(user)
	return f"(`tabSP Campaign`.owner_user = {u} or `tabSP Campaign`.owner = {u})"


def has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if doc.is_new() or _sees_all(user):
		return True
	return user in (doc.get("owner_user"), doc.owner)


@frappe.whitelist()
def active_campaigns() -> list[dict]:
	"""For "Record spend" and the request form: the campaigns the user may choose."""
	return frappe.get_list(
		CAMPAIGN, filters={"status": ACTIVE}, fields=["name", "campaign_name"], order_by="start_date desc"
	)


@frappe.whitelist(methods=["POST"])
def close_campaign(campaign: str) -> None:
	doc = frappe.get_doc(CAMPAIGN, campaign)
	doc.check_permission("write")
	refresh(campaign)
	doc.reload()
	doc.status = CLOSED
	doc.end_date = doc.end_date or getdate()
	doc.save()


@frappe.whitelist(methods=["POST"])
def recount(campaign: str) -> dict:
	frappe.get_doc(CAMPAIGN, campaign).check_permission("read")
	return refresh(campaign)


@frappe.whitelist()
def spend_options(campaign: str) -> dict:
	"""For "Record spend": the user's open custodies, the Marketing expense type and the
	Indirect Pool center of each custody's company (the expense lands there, ERD 7.4)."""
	from smart_power.sp_core.services.lists import by_code
	from smart_power.sp_finance.centers import INDIRECT, center

	frappe.get_doc(CAMPAIGN, campaign).check_permission("read")
	custodies = frappe.get_all(
		"SP Custody",
		filters={
			"holder": frappe.session.user,
			"docstatus": SUBMITTED,
			"status": ("not in", ("Returned", "Cancelled")),
		},
		fields=["name", "company", "balance", "given_on"],
		order_by="given_on desc",
	)
	for c in custodies:
		c.cost_center = center(INDIRECT, c.company)
	return {"custodies": custodies, "expense_type": by_code("Expense Type", "MARKETING")}
