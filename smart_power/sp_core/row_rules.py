"""Row rules of the permissions matrix (X2, SP-131): "assigned to me".

A role with an SP Role Row Rule on a document type sees only the documents assigned to its user:

    SP Case             its follow-up owner or its quote creator
    SP Station          its execution owner
    SP Task             its assignee
    SP Service Ticket   its assignee

The rule restricts a user only when every role that lets them read the type carries it: one
role without the rule keeps the user's wider view, as Frappe's "only if creator" does (the
automatic roles, such as Desk User, don't count). The admin is never restricted. "Own records" is Frappe's own if_owner and needs nothing here.
"""

import frappe

RULE, ASSIGNED = "SP Role Row Rule", "Assigned to me"
ADMIN = ("Administrator",)
ADMIN_ROLES = ("SP Admin", "System Manager")
AUTOMATIC = ("All", "Guest", "Desk User")  # every user has them: they never widen the view
ASSIGNEE = {
	"SP Case": ("follow_up_owner", "quote_creator"),
	"SP Station": ("execution_owner",),
	"SP Task": ("assigned_to",),
	"SP Service Ticket": ("assigned_to",),
}


def readers(doctype: str, roles) -> set[str]:
	"""The roles among `roles` that may read the type (permission level 0)."""
	return {
		p.role
		for p in frappe.get_meta(doctype).permissions
		if p.role in roles and p.role not in AUTOMATIC and not p.permlevel and p.read
	}


def restricted(doctype: str, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if doctype not in ASSIGNEE or user in ADMIN:
		return False
	roles = set(frappe.get_roles(user))
	if roles & set(ADMIN_ROLES):
		return False
	ruled = set(frappe.get_all(RULE, {"document_type": doctype, "rule": ASSIGNED}, pluck="role"))
	reading = readers(doctype, roles)
	return bool(ruled and reading and reading <= ruled)


def query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	"""permission_query_conditions, beside each type's own: only the user's assigned rows."""
	if not doctype or not restricted(doctype, user):
		return ""
	u = frappe.db.escape(user or frappe.session.user)
	table = f"`tab{doctype}`"
	return "(" + " or ".join(f"{table}.`{f}` = {u}" for f in ASSIGNEE[doctype]) + ")"


def has_permission(doc, ptype: str | None = None, user: str | None = None, **kwargs) -> bool:
	"""has_permission, beside each type's own: a restricted user's documents are their own."""
	if doc.is_new() or not restricted(doc.doctype, user):
		return True
	user = user or frappe.session.user
	return user in [doc.get(f) for f in ASSIGNEE[doc.doctype]]
