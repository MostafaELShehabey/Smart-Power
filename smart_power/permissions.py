"""Who sees what (SP-35).

Cost, supplier prices and the P1 list are for the cost roles only: the admin, the accountant,
quote creators, pricing managers, the purchase officer and supplier accounts (the
`sees_cost` flag in the role catalogue). Everyone else sees sale prices only.

This module holds the checks; the hooks in hooks.py apply them to ERPNext's own DocTypes, and
APIs strip the cost keys before they answer. A quote follows its case's row rule; its cost,
profit and hidden lines are for its own creator and the admin only.
"""

import frappe
from frappe import _

from smart_power.sp_core.setup.role_catalogue import COST_ROLES

# Keys every API removes for users without cost access.
COST_KEYS = ("cost", "cost_date", "cost_supplier", "list_price", "list_date", "list_supplier", "margin_pct")


def can_see_cost(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(COST_ROLES) & set(frappe.get_roles(user)))


def strip_cost(data: dict, user: str | None = None) -> dict:
	"""A copy of data without the cost keys, unless the user may see cost."""
	if can_see_cost(user):
		return data
	return {k: v for k, v in data.items() if k not in COST_KEYS}


# --- Item Price: buying prices (List Price, P1 Cost, supplier prices) ---------------------------


def item_price_query_conditions(user: str | None = None) -> str:
	"""permission_query_conditions for Item Price: buying rows only for cost roles."""
	if can_see_cost(user):
		return ""
	return "(`tabItem Price`.buying = 0)"


def item_price_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""has_permission for Item Price. Controllers can only deny; True keeps the role's rights."""
	if doc.get("buying") and not can_see_cost(user):
		return False
	return True


# --- SP Case: who sees a case (SP-35, with SP-46) ---------------------------------------------

# Roles that see every case: the admin and the call centre lead who follows all cases (كاميليا).
CASE_SEES_ALL = ("SP Admin", "System Manager", "SP Followup All")
QUOTE_CREATOR = "SP Quote Creator"
OPEN_REQUEST = "Quote request"
# The contracts team: sees the cases with an approved version, and keeps them after the contract.
CONTRACT_ROLES = ("SP Contract Manager", "SP Project Manager")


def _case_sees_all(user: str) -> bool:
	return user == "Administrator" or bool(set(CASE_SEES_ALL) & set(frappe.get_roles(user)))


def case_query_conditions(user: str | None = None) -> str:
	"""permission_query_conditions for SP Case: a case is seen by its requester, quote creator
	and follow-up owner; quote creators also see unclaimed quote requests (to take them)."""
	user = user or frappe.session.user
	if _case_sees_all(user):
		return ""
	u = frappe.db.escape(user)
	cond = f"(`tabSP Case`.follow_up_owner = {u} or `tabSP Case`.requested_by = {u} or `tabSP Case`.quote_creator = {u}"
	roles = frappe.get_roles(user)
	if QUOTE_CREATOR in roles:
		cond += f" or (`tabSP Case`.status = {frappe.db.escape(OPEN_REQUEST)} and ifnull(`tabSP Case`.quote_creator, '') = '')"
	if set(CONTRACT_ROLES) & set(roles):
		# the contracts team takes a case once a version is approved (أميرة)
		cond += " or ifnull(`tabSP Case`.accepted_quotation, '') != ''"
	return cond + ")"


def case_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""has_permission for SP Case, the same rule for one document; read-only after the contract."""
	user = user or frappe.session.user
	if doc.is_new():
		return True
	if ptype not in READ_PTYPES and read_only_after_contract(doc.name, user):
		return False
	if _case_sees_all(user):
		return True
	if user in (doc.follow_up_owner, doc.requested_by, doc.quote_creator):
		return True
	roles = frappe.get_roles(user)
	if set(CONTRACT_ROLES) & set(roles) and frappe.db.get_value("SP Case", doc.name, "accepted_quotation"):
		return True
	if QUOTE_CREATOR not in roles:
		return False
	# "Unclaimed" is judged on the saved case: while a quote creator takes a request, the
	# document being saved already says Draft, before its quote creator is filled in.
	stored = frappe.db.get_value("SP Case", doc.name, ["status", "quote_creator"], as_dict=True) or doc
	return bool(stored.status == OPEN_REQUEST and not stored.quote_creator)


# --- Quotation: cost and profit for cost roles only (SP-35, with SP-54) ------------------------

# Cost fields on the quote live at permlevel 2 (Cost, Line Profit, Total Cost, Profit, Margin).
# ERPNext already uses permlevel 1 on Quotation and gives it to Sales User, so 2 is ours.
COST_PERMLEVEL = 2  # sp-allow-number: Frappe permission level, not a business value
# Supplier prices on purchase orders: the purchase officer (أميرة), the admin, the accountant and
# supplier accounts; the purchase officer and the admin also type them.
PO_COST_ROLES = ("SP Admin", "SP Purchase Officer", "SP Accountant", "SP Supplier Accounts")
# {doctype: (roles that read the cost permlevel, roles that also write it)}
COST_DOCTYPES = {
	"Quotation": (COST_ROLES, ("SP Admin", "SP Quote Creator", "SP System Designer")),
	"Purchase Order": (PO_COST_ROLES, ("SP Admin", "SP Purchase Officer")),
	# receivers save the draft receipt and never see what the goods cost (SP-84)
	"Purchase Receipt": (PO_COST_ROLES, ("SP Admin", "SP Purchase Officer")),
}


def sync_cost_permissions() -> None:
	"""Give the cost roles read (and some write) at the cost permlevel on Quotation and Purchase
	Order; never remove rows.

	Uses Frappe's own add_permission, which copies the standard rules into Role Permissions
	the first time (as the Role Permissions Manager does). Rows the admin changed are kept.
	"""
	from frappe.permissions import add_permission, update_permission_property

	for doctype, (readers, writers) in COST_DOCTYPES.items():
		for role in readers:
			if not frappe.db.exists("Role", role):
				continue
			key = {"parent": doctype, "role": role, "permlevel": COST_PERMLEVEL, "if_owner": 0}
			if not frappe.db.exists("Custom DocPerm", key):
				add_permission(doctype, role, COST_PERMLEVEL)
				if role in writers:
					update_permission_property(doctype, role, COST_PERMLEVEL, "write", 1, validate=False)
		frappe.clear_cache(doctype=doctype)


# Quote cost and profit keys (permlevel COST_PERMLEVEL): header and line.
QUOTE_COST_KEYS = ("sp_total_cost", "sp_profit", "sp_margin_pct")
QUOTE_LINE_COST_KEYS = ("sp_cost", "sp_line_profit")


# --- After the contract: the case, its quotes and its station are read-only for sales ----------

# What a read-only user may still do.
READ_PTYPES = (None, "read", "select", "print", "email", "report", "export", "share")
# Who keeps working on a case once it has its contract (أميرة's roles, and the admin).
AFTER_CONTRACT_WRITERS = ("SP Admin", "System Manager", "SP Contract Manager", "SP Project Manager")
STATION, CANCELLED = "SP Station", "Cancelled"


def contract_station(case: str | None) -> str | None:
	"""The case's station once the case is won (its contract made), else None."""
	if not case or frappe.db.get_value("SP Case", case, "status") != "Won":
		return None
	return frappe.db.get_value(STATION, {"case": case, "status": ("!=", CANCELLED)})


def read_only_after_contract(case: str | None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator" or set(AFTER_CONTRACT_WRITERS) & set(frappe.get_roles(user)):
		return False
	return bool(contract_station(case))


def read_only_banner(case: str | None, user: str | None = None) -> str | None:
	"""'Read-only — now with أميرة': who the case is with after its contract."""
	if not read_only_after_contract(case, user):
		return None
	station = frappe.db.get_value(
		STATION, contract_station(case), ["execution_owner", "sales_order"], as_dict=True
	)
	holder = station.execution_owner or (
		station.sales_order and frappe.db.get_value("Sales Order", station.sales_order, "owner")
	)
	name = frappe.utils.get_fullname(holder) if holder else _("the projects team")
	return _("Read-only — now with {0}").format(name)


def set_read_only_banner(doc, method=None) -> None:
	"""onload of SP Case, Quotation and SP Station: the banner text for the form."""
	case = doc.name if doc.doctype == "SP Case" else doc.get("sp_case") or doc.get("case")
	banner = read_only_banner(case)
	if banner:
		doc.set_onload("sp_read_only", banner)


# --- Customer: featured for all, the rest for their owners (SP-50) -------------------------------

# Roles that work with every customer: the admin, the follow-up lead, and the money and
# execution roles that serve every station's customer.
CUSTOMER_SEES_ALL = (
	"SP Admin",
	"System Manager",
	"SP Followup All",
	"SP Accountant",
	"SP Collection Officer",
	"SP Contract Manager",
	"SP Project Manager",
	"SP Bank Financing",
	"SP Showroom Cashier",
	"SP Commission Manager",
)


def _customer_sees_all(user: str) -> bool:
	return user == "Administrator" or bool(set(CUSTOMER_SEES_ALL) & set(frappe.get_roles(user)))


def customer_query_conditions(user: str | None = None) -> str:
	"""permission_query_conditions for Customer: a featured customer (one with a won deal) is seen
	by everyone; any other by its owner, by whoever works on one of its cases, and, while it has
	neither owner nor case, by everyone."""
	user = user or frappe.session.user
	if _customer_sees_all(user):
		return ""
	u = frappe.db.escape(user)
	cases = (
		"select 1 from `tabSP Case` c where c.customer = `tabCustomer`.name and "
		f"(c.follow_up_owner = {u} or c.requested_by = {u} or c.quote_creator = {u})"
	)
	any_case = "select 1 from `tabSP Case` c where c.customer = `tabCustomer`.name"
	return (
		f"(ifnull(`tabCustomer`.sp_featured, 0) = 1 or `tabCustomer`.sp_owner_user = {u} or exists ({cases})"
		f" or (ifnull(`tabCustomer`.sp_owner_user, '') = '' and not exists ({any_case})))"
	)


def customer_is_mine(customer: str, user: str) -> bool:
	"""The owner, or someone working on one of its cases, or no one's customer yet."""
	owner = frappe.db.get_value("Customer", customer, "sp_owner_user")
	if owner == user:
		return True
	cases = frappe.get_all(
		"SP Case", {"customer": customer}, ["follow_up_owner", "requested_by", "quote_creator"]
	)
	if any(user in (c.follow_up_owner, c.requested_by, c.quote_creator) for c in cases):
		return True
	return not owner and not cases


def customer_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""has_permission for Customer: the same rule for one customer. A featured customer of
	someone else is read-only (its overview, never its edits)."""
	user = user or frappe.session.user
	if doc.is_new() or _customer_sees_all(user):
		return True
	if customer_is_mine(doc.name, user):
		return True
	return bool(doc.get("sp_featured")) and ptype in READ_PTYPES


# --- SP Station: whoever is assigned to it -------------------------------------------------------

# Roles that see every station.
STATION_SEES_ALL = (
	"System Manager",
	"SP Admin",
	"SP Project Manager",
	"SP Installation Manager",
	"SP Winch Manager",  # books the station's winch jobs (SP-107)
	"SP Followup All",
	"SP Accountant",
)


def _station_sees_all(user: str) -> bool:
	return user == "Administrator" or bool(set(STATION_SEES_ALL) & set(frappe.get_roles(user)))


def station_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	"""permission_query_conditions for SP Station: its execution, collection and sales owners, and
	(read-only) its case's quote creator and follow-up owner."""
	user = user or frappe.session.user
	if _station_sees_all(user):
		return ""
	u = frappe.db.escape(user)
	t = "`tabSP Station`"
	return (
		f"({t}.execution_owner = {u} or {t}.collection_owner = {u} or {t}.sales_owner = {u}"
		f" or {t}.`case` in (select name from `tabSP Case` where quote_creator = {u} or follow_up_owner = {u}))"
	)


def station_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""has_permission for SP Station, the same rule for one station. Its sales owner and its
	case's quote creator and follow-up owner only read it."""
	user = user or frappe.session.user
	if doc.is_new() or _station_sees_all(user):
		return True
	if user in (doc.execution_owner, doc.collection_owner):
		return True
	owners = (
		frappe.db.get_value("SP Case", doc.case, ["quote_creator", "follow_up_owner"]) if doc.case else None
	)
	reader = user == doc.sales_owner or user in (owners or ())
	return reader and ptype in READ_PTYPES


# --- Quotation: rows follow the case; cost and hidden lines for its creator and the admin ------

# Roles that see the cost, the profit and the hidden lines of every quote.
QUOTE_INTERNALS_ALL = ("SP Admin", "System Manager")


def sees_quote_internals(doc, user: str | None = None) -> bool:
	"""Cost, profit and hidden lines: the admin, and the quote's own creator (the case's quote
	creator, or whoever made the quote) when they hold a cost role (SP-35)."""
	user = user or frappe.session.user
	if user == "Administrator" or set(QUOTE_INTERNALS_ALL) & set(frappe.get_roles(user)):
		return True
	if not can_see_cost(user):
		return False
	if doc.is_new() or user in (doc.get("owner"), doc.get("sp_quote_creator")):
		return True
	case = doc.get("sp_case")
	return bool(case) and frappe.db.get_value("SP Case", case, "quote_creator") == user


def quote_query_conditions(user: str | None = None) -> str:
	"""permission_query_conditions for Quotation: a case's quote is seen by whoever sees the case."""
	user = user or frappe.session.user
	cases = case_query_conditions(user)
	if not cases:
		return ""
	return f"(ifnull(`tabQuotation`.sp_case, '') = '' or `tabQuotation`.sp_case in (select name from `tabSP Case` where {cases}))"


def quote_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""has_permission for Quotation, the same rule for one quote; read-only after the contract."""
	user = user or frappe.session.user
	if doc.is_new() or not doc.get("sp_case"):
		return True
	if ptype not in READ_PTYPES and read_only_after_contract(doc.sp_case, user):
		return False
	if _case_sees_all(user):
		return True
	return case_has_permission(frappe.get_doc("SP Case", doc.sp_case), "read", user)


def strip_quote_internals(doc, user: str | None = None) -> None:
	"""Leave the cost, profit and hidden lines out of a loaded quote, for those who may not see them.

	Field permissions already hide cost from the non-cost roles; this also hides it on another
	creator's quote and takes the hidden lines out (form, REST, get_quote_view)."""
	if sees_quote_internals(doc, user):
		return
	for key in QUOTE_COST_KEYS:
		if hasattr(doc, key):
			delattr(doc, key)
	doc.set("items", [row for row in doc.get("items") or [] if not row.get("sp_is_hidden")])
	for table in ("items", "sp_optional_lines"):
		for row in doc.get(table) or []:
			for key in QUOTE_LINE_COST_KEYS:
				if hasattr(row, key):
					delattr(row, key)


def keep_quote_internals(doc, method=None) -> None:
	"""Quotation before_validate: a user who was shown the quote without its cost or hidden lines
	saves it without them, so the stored ones are put back (SP-35)."""
	if doc.is_new() or sees_quote_internals(doc):
		return
	stored = frappe.get_all(
		"Quotation Item",
		filters={"parent": doc.name, "parenttype": "Quotation"},
		fields=["*"],
		order_by="idx asc",
	)
	by_name = {row.name: row for row in stored}
	present = {row.name for row in doc.items}
	for row in doc.items:
		old = by_name.get(row.name)
		if old:
			for key in QUOTE_LINE_COST_KEYS:
				row.set(key, old.get(key))
	for old in stored:
		if old.sp_is_hidden and old.name not in present:
			doc.append(
				"items",
				{
					k: v
					for k, v in old.items()
					if k not in ("idx", "parent", "parentfield", "parenttype", "doctype")
				},
			)


@frappe.whitelist()
def get_quote_view(name: str) -> dict:
	"""A quote as its reader may see it: without the cost and profit keys for non-cost roles.

	Plain REST already hides their values (Frappe sends 0 for a field the reader cannot see);
	this view leaves the keys out altogether (SP-35, SP-54).
	"""
	doc = frappe.get_doc("Quotation", name)
	doc.check_permission("read")
	doc.apply_fieldlevel_read_permissions()  # also strips the internals (SPQuotation)
	data = doc.as_dict()
	if sees_quote_internals(doc):
		return data
	for key in QUOTE_COST_KEYS:
		data.pop(key, None)
	for table in ("items", "sp_optional_lines"):
		for row in data.get(table) or []:
			for key in QUOTE_LINE_COST_KEYS:
				row.pop(key, None)
	return data


# --- Payment Entry: a customer payment is seen by its recorder, its collector and the admin ----

# Roles that see every customer payment (they confirm and post them).
PAYMENT_SEES_ALL = ("SP Admin", "System Manager", "SP Accountant")


def _payment_sees_all(user: str) -> bool:
	return user == "Administrator" or bool(set(PAYMENT_SEES_ALL) & set(frappe.get_roles(user)))


def payment_query_conditions(user: str | None = None) -> str:
	"""permission_query_conditions for Payment Entry: a payment on a case is seen by whoever
	recorded it and by the collection owner of the case's station (SP-35); others stay as ERPNext has them."""
	user = user or frappe.session.user
	if _payment_sees_all(user):
		return ""
	u = frappe.db.escape(user)
	t = "`tabPayment Entry`"
	return (
		f"(ifnull({t}.sp_case, '') = '' or {t}.owner = {u}"
		f" or {t}.sp_case in (select `case` from `tabSP Station` where collection_owner = {u}))"
	)


def payment_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""has_permission for Payment Entry, the same rule for one payment."""
	user = user or frappe.session.user
	if doc.is_new() or not doc.get("sp_case") or _payment_sees_all(user) or doc.owner == user:
		return True
	return bool(frappe.db.exists(STATION, {"case": doc.sp_case, "collection_owner": user}))


def customer_payment_query_conditions(user: str | None = None) -> str:
	"""permission_query_conditions for SP Customer Payment: its recorder, the collection owner of
	its station, and the admin and accountant (SP-35)."""
	user = user or frappe.session.user
	if _payment_sees_all(user):
		return ""
	u = frappe.db.escape(user)
	t = "`tabSP Customer Payment`"
	return (
		f"({t}.owner = {u} or {t}.recorded_by = {u}"
		f" or {t}.station in (select name from `tabSP Station` where collection_owner = {u}))"
	)


def customer_payment_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""has_permission for SP Customer Payment, the same rule for one payment."""
	user = user or frappe.session.user
	if doc.is_new() or _payment_sees_all(user) or user in (doc.owner, doc.get("recorded_by")):
		return True
	return bool(doc.station) and frappe.db.get_value(STATION, doc.station, "collection_owner") == user
