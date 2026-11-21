"""RV2 Review centre (SP-129): everything that happened outside the normal path, for the admin.

The admin controls after the fact instead of approving each step: module stories raise SP
Review Items (raise_item, or the rules engine through open_review_item) and the admin goes
through them by tab here:

    tabs()                            the tabs with their open counts (and AD1's attention count)
    items(category, status)           the items of one tab
    mark_reviewed(names, comment)     one or many items, at once
    comment(name, comment, to_user)   a comment to the record's owner, who is notified with a link
    forward(name, to_user, note)      hand the item to another reviewer (an assignment)

A reversal (JE reversal, payment rejection) comes with the accounting stories that raise those
items. Every discount on a quote is listed (Discounts tab), highlighted above the quote
creator's limit (Smart Power Settings, 4% at go-live).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_fullname

from smart_power.sp_core.services.review import open_review_item

ITEM = "SP Review Item"
OPEN, REVIEWED = "Open", "Reviewed"
# the RV2 tabs in their order; every category of SP Review Item has a tab
TABS = (
	"Margin",
	"Discount",
	"Override",
	"Edit",
	"Manual Entry",
	"Late Entry",
	"Abnormal",
	"Change Order",
	"Reassignment",
	"Consignment Conversion",
	"Write-off",
	"Rule Warning",
	"PO Sent",
	"Count Difference",
	"Station Cancellation",
)
PAGE_SIZE = 200  # sp-allow-number: items listed per tab, a screen size


def raise_item(category: str, doc, summary: str, amount: float | None = None, highlight: bool = False):
	"""The service module stories call to list something for the admin (RV2)."""
	return open_review_item(
		category=category,
		reference_doctype=doc.doctype,
		reference_name=doc.name,
		summary=summary,
		amount=amount,
		highlight=highlight,
	)


def _check_reviewer() -> None:
	frappe.has_permission(ITEM, "write", throw=True)


def _labels() -> dict[str, str]:
	return {
		"Margin": _("Margin out of range"),
		"Discount": _("Discounts"),
		"Override": _("Rule overrides"),
		"Edit": _("Edits with reason"),
		"Manual Entry": _("Manual entries"),
		"Late Entry": _("Late and reopened field entries"),
		"Abnormal": _("Abnormal flags"),
		"Change Order": _("Change orders"),
		"Reassignment": _("Reassignments"),
		"Consignment Conversion": _("Consignment conversions"),
		"Write-off": _("Write-offs"),
		"Station Cancellation": _("Station cancellations"),
		"Rule Warning": _("Rule warnings"),
		"PO Sent": _("Purchase orders sent"),
		"Count Difference": _("Count differences"),
	}


@frappe.whitelist()
def tabs() -> dict:
	"""The tabs with their open and highlighted counts; `open` is AD1's attention count."""
	_check_reviewer()
	open_items = frappe.get_all(ITEM, filters={"status": OPEN}, fields=["category", "highlight"])
	counts, highlighted = {}, {}
	for row in open_items:
		counts[row.category] = counts.get(row.category, 0) + 1
		highlighted[row.category] = highlighted.get(row.category, 0) + cint(row.highlight)
	labels = _labels()
	return {
		"tabs": [
			{
				"category": c,
				"label": labels[c],
				"open": counts.get(c, 0),
				"highlighted": highlighted.get(c, 0),
			}
			for c in TABS
		],
		"open": len(open_items),
	}


def attention_count() -> int:
	"""Open review items, for the AD1 attention list (SP-138)."""
	return frappe.db.count(ITEM, {"status": OPEN})


@frappe.whitelist()
def items(category: str, status: str = OPEN) -> list[dict]:
	_check_reviewer()
	if category not in TABS:
		frappe.throw(_("Unknown review tab {0}.").format(frappe.bold(category)))
	rows = frappe.get_all(
		ITEM,
		filters={"category": category, "status": status},
		fields=[
			"name",
			"reference_doctype",
			"reference_name",
			"summary",
			"amount",
			"highlight",
			"reason",
			"comment",
			"raised_by",
			"creation",
			"reviewed_by",
			"reviewed_on",
		],
		order_by="highlight desc, creation desc",
		limit_page_length=PAGE_SIZE,
	)
	for row in rows:
		row.raised_by_name = get_fullname(row.raised_by) if row.raised_by else ""
		row.owner = owner_of(row)
		row.owner_name = get_fullname(row.owner) if row.owner else ""
	return rows


def owner_of(item) -> str | None:
	"""Who answers for the record: the quote's creator, the case's follow-up owner, else whoever
	made the record or raised the item."""
	doctype, name = item.get("reference_doctype"), item.get("reference_name")
	owner = None
	if doctype and name and frappe.db.exists(doctype, name):
		if doctype == "Quotation":
			owner = frappe.db.get_value(doctype, name, "sp_quote_creator")
		elif doctype == "SP Case":
			owner = frappe.db.get_value(doctype, name, "follow_up_owner")
		owner = owner or frappe.db.get_value(doctype, name, "owner")
	return owner or item.get("raised_by")


@frappe.whitelist(methods=["POST"])
def mark_reviewed(names: str | list, comment: str | None = None) -> int:
	"""Mark one or many items reviewed (bulk), with an optional comment."""
	_check_reviewer()
	names = frappe.parse_json(names) if isinstance(names, str) else names
	done = 0
	for name in names or []:
		doc = frappe.get_doc(ITEM, name)
		if doc.status == REVIEWED:
			continue
		doc.status = REVIEWED
		if comment:
			doc.comment = comment
		doc.flags.ignore_links = True
		doc.save()
		done += 1
	return done


@frappe.whitelist(methods=["POST"])
def comment(name: str, comment: str, to_user: str | None = None) -> str:
	"""A comment to the record's owner: kept on the item and on the record, and the owner is
	notified with a link to the record."""
	_check_reviewer()
	comment = (comment or "").strip()
	if not comment:
		frappe.throw(_("Write the comment first."))
	doc = frappe.get_doc(ITEM, name)
	to_user = to_user or owner_of(doc)
	doc.comment = comment
	doc.flags.ignore_links = True
	doc.save()
	if doc.reference_doctype and frappe.db.exists(doc.reference_doctype, doc.reference_name):
		frappe.get_doc(doc.reference_doctype, doc.reference_name).add_comment(
			"Comment", _("Review: {0}").format(comment)
		)
	if to_user:
		_notify(doc, to_user, _("{0} reviewed {1}: {2}").format(get_fullname(), doc.reference_name, comment))
	return to_user or ""


@frappe.whitelist(methods=["POST"])
def forward(name: str, to_user: str, note: str | None = None) -> str:
	"""Hand the item to another reviewer: an assignment on the item, and a notification."""
	from frappe.desk.form.assign_to import add as assign

	_check_reviewer()
	doc = frappe.get_doc(ITEM, name)
	if not frappe.has_permission(ITEM, "write", user=to_user):
		frappe.throw(
			_("{0} cannot review; forward it to the admin.").format(frappe.bold(get_fullname(to_user)))
		)
	assign({"assign_to": [to_user], "doctype": ITEM, "name": doc.name, "description": note or doc.summary})
	return to_user


def _notify(doc, user: str, subject: str) -> None:
	from smart_power.notify import send

	# the link opens the record the owner can read, not the review item
	send(
		"review_comment",
		[user],
		doc.reference_doctype or ITEM,
		doc.reference_name or doc.name,
		subject,
		from_user=frappe.session.user,
	)


# --- every discount is listed (SP-68 / SP-129) ---------------------------------------------------


def list_quote_discount(doc, method=None) -> None:
	"""Quotation on_update: a raised discount on a case's quote is listed in the Discounts tab,
	highlighted above the quote creator's limit. Above-limit rules already opened the same item."""
	from smart_power.rules.commercial import total_discount_pct
	from smart_power.sp_core.services.settings import get_value

	if not doc.get("sp_case"):
		return
	pct = total_discount_pct(doc)
	amount = flt(doc.discount_amount)
	if not pct:
		return
	ref = {"category": "Discount", "reference_doctype": doc.doctype, "reference_name": doc.name}
	# listed once per amount: an unchanged discount on a later save is not listed again
	if frappe.db.exists(ITEM, {**ref, "amount": amount, "status": REVIEWED}):
		return
	limit = flt(get_value("creator_discount_max_pct"))
	highlight = bool(limit and pct > limit)
	existing = frappe.db.get_value(ITEM, {**ref, "status": OPEN})
	if existing:  # a limit rule (or an earlier save) listed it: keep its message, refresh the amount
		frappe.db.set_value(ITEM, existing, {"amount": amount, "highlight": int(highlight)})
		return
	open_review_item(
		category="Discount",
		reference_doctype=doc.doctype,
		reference_name=doc.name,
		summary=_("Discount {0}% ({1}) on quote {2}").format(
			frappe.format(pct, "Float"),
			frappe.format(doc.discount_amount, {"fieldtype": "Currency", "options": doc.currency}),
			doc.name,
		),
		amount=amount,
		highlight=highlight,
	)
