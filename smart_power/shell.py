"""The app shell (SP-37): Smart Power's dock of module-group sidebars.

The groups are shipped as `Sidebar` documents (<module>/sidebar) on the app's `Dock`
(smart_power/dock). Frappe already drops a sidebar item the user cannot open, but ERPNext's base
roles read most masters (Item, Customer, Sales Order ...), so that alone would show almost every
group to almost everyone. A group is therefore shown only to the roles that work in it
(GROUP_ROLES), and a few items only to the roles that use them (ITEM_ROLES). This is navigation
only: what a user may open is still decided by the permissions.

    apply_to_boot(bootinfo)   boot_session: drop the groups and items this user does not work in
    get_new_menu()            "+ New": only what the user may start (NEW_ACTIONS)
    get_counts()              unread notifications and waiting tasks, for the dock

sp_shell.js puts "+ New" and My Tasks (with its count) in the dock; the count follows every task
change at once (realtime sp_tasks).
"""

import frappe
from frappe import _

APP = "smart_power"
ADMIN = ("SP Admin", "System Manager")
EVERYONE = None

# group (Sidebar title) → the roles that see it; EVERYONE for all desk users
GROUP_ROLES = {
	"Smart Power": EVERYONE,
	"Requests & Customers": (
		"SP Lead Intake",
		"SP Customer Followup",
		"SP Followup All",
		"SP Marketing Agent",
		"SP Quote Creator",
		"SP Showroom Sales",
		*ADMIN,
	),
	"Follow-up": ("SP Customer Followup", "SP Followup All", "SP Collection Officer", *ADMIN),
	"Quotes": ("SP Quote Creator", "SP System Designer", "SP Followup All", "SP Pricing Manager", *ADMIN),
	"Stations": (
		"SP Project Manager",
		"SP Installation Manager",
		"SP Contract Manager",
		"SP Collection Officer",
		"SP Customer Followup",
		"SP Followup All",
		"SP Accountant",
		"SP Regulatory Compliance",
		*ADMIN,
	),
	"Purchasing": (
		"SP Purchase Officer",
		"SP Receipt Confirmer",
		"SP Main Store Keeper",
		"SP Showroom Store Keeper",
		"SP Site Receiver",
		"SP Supplier Accounts",
		*ADMIN,
	),
	"Inventory": (
		"SP Installation Manager",
		"SP Main Store Keeper",
		"SP Showroom Store Keeper",
		"SP Site Receiver",
		"SP Purchase Officer",
		"SP Catalog Manager",
		"SP Project Manager",
		*ADMIN,
	),
	"Winch": ("SP Winch Manager", "SP Winch Reviewer", *ADMIN),
	"Finance": (
		"SP Accountant",
		"SP Collection Officer",
		"SP Showroom Cashier",
		"SP Custody Holder",
		"SP Bank Financing",
		"SP Supplier Accounts",
		"SP Commission Manager",
		*ADMIN,
	),
	"Reports": ("SP Accountant", *ADMIN),
	"Admin Studio": ADMIN,
}

# (group, item label) → the roles that see that item inside its group
ITEM_ROLES = {
	("Requests & Customers", "Campaigns"): ("SP Marketing Agent", "SP Followup All", *ADMIN),
	("Requests & Customers", "Leads"): ("SP Marketing Agent", "SP Lead Intake", "SP Followup All", *ADMIN),
	("Requests & Customers", "Import Leads"): ("SP Marketing Agent", "SP Lead Intake", *ADMIN),
	("Purchasing", "Purchase Orders"): ("SP Purchase Officer", "SP Supplier Accounts", *ADMIN),
	("Purchasing", "Suppliers"): ("SP Purchase Officer", "SP Supplier Accounts", *ADMIN),
	("Purchasing", "Supplier Ledger"): ("SP Supplier Accounts", "SP Accountant", *ADMIN),
	("Purchasing", "Consignment Containers"): ("SP Purchase Officer", "SP Main Store Keeper", *ADMIN),
	("Stations", "Contracts"): ("SP Contract Manager", "SP Project Manager", "SP Accountant", *ADMIN),
	# qualification and compliance (RG1, SP-101)
	("Stations", "Installed Capacity"): ("SP Regulatory Compliance", *ADMIN),
	("Stations", "Compliance Documents"): ("SP Regulatory Compliance", *ADMIN),
	("Stations", "Compliance Reports"): ("SP Regulatory Compliance", *ADMIN),
}


def _allowed(roles, user_roles: set) -> bool:
	return roles is EVERYONE or bool(set(roles) & user_roles)


def visible_groups(user: str | None = None) -> dict[str, set]:
	"""{group: the item labels hidden in it} for each group the user works in."""
	user = user or frappe.session.user
	if user == "Administrator":
		return {group: set() for group in GROUP_ROLES}
	roles = set(frappe.get_roles(user))
	return {
		group: {
			label
			for (g, label), item_roles in ITEM_ROLES.items()
			if g == group and not _allowed(item_roles, roles)
		}
		for group, group_roles in GROUP_ROLES.items()
		if _allowed(group_roles, roles)
	}


def apply_to_boot(bootinfo) -> None:
	"""boot_session: keep only the groups (and items) the user works in, everywhere the desk reads
	them: the sidebars, the dock, the app's entry set, and the shells routes open in."""
	visible = visible_groups()
	hidden = set(GROUP_ROLES) - set(visible)
	sidebars = bootinfo.get("module_sidebars") or {}
	for group in hidden:
		sidebars.pop(group, None)
	for group, labels in visible.items():
		if labels and group in sidebars:
			# the boot's labels are already in the user's language
			labels = labels | {_(label) for label in labels}
			sidebars[group]["items"] = [i for i in sidebars[group]["items"] if i.get("label") not in labels]

	def keep(row) -> bool:
		return not (row.get("link_type") == "Sidebar" and row.get("link_to") in hidden)

	dock = bootinfo.get("dock") or {}
	if dock.get(APP):
		dock[APP] = [row for row in dock[APP] if keep(row)]
	for app in bootinfo.get("app_data") or []:
		if app.get("app_name", app.get("name")) == APP and app.get("dock"):
			app["dock"] = [row for row in app["dock"] if keep(row)]
	if bootinfo.get("home_shell") in hidden:
		bootinfo.home_shell = "Smart Power"
	for shells in (bootinfo.get("canonical_shell") or {}).values():
		if isinstance(shells, dict):
			for entity in [e for e, shell in shells.items() if shell in hidden]:
				shells.pop(entity)


# --- "+ New" and the counts ------------------------------------------------------------------------

# What "+ New" can start, in order: (key, label, kind, target, doctype checked for create, roles).
# kind: page (open it), new (a new document), dialog (the module's own dialog, in sp_shell.js).
# Showroom sale, expense and winch booking join here when those stories land.
NEW_ACTIONS = (
	(
		"quote_request",
		"Quote Request",
		"page",
		"sp-quote-request",
		None,
		("SP Lead Intake", "SP Customer Followup", "SP Marketing Agent", *ADMIN),
	),
	# a quick sale price for a walk-in or a caller (SP-49)
	(
		"indicative_price",
		"Indicative Price",
		"page",
		"sp-indicative-price",
		None,
		("SP Lead Intake", "SP Customer Followup", "SP Marketing Agent", *ADMIN),
	),
	("payment", "Payment on a Station", "dialog", "payment", "SP Customer Payment", None),
	("transfer", "Deposit or Transfer", "dialog", "transfer", "SP Transfer", None),
	# a one-off record with its own simple entry: a storage fee, a small income (SP-43)
	("simple_record", "Simple Record", "new", "SP Simple Record", "SP Simple Record", None),
	("customer", "Customer", "new", "Customer", "Customer", None),
	(
		"purchase_order",
		"Purchase Order",
		"new",
		"Purchase Order",
		"Purchase Order",
		("SP Purchase Officer", *ADMIN),
	),
)


@frappe.whitelist()
def get_new_menu() -> list[dict]:
	"""The "+ New" menu: only what this user may start."""
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	menu = []
	for key, label, kind, target, doctype, action_roles in NEW_ACTIONS:
		if action_roles and user != "Administrator" and not set(action_roles) & roles:
			continue
		if doctype and not (
			frappe.db.exists("DocType", doctype) and frappe.has_permission(doctype, "create", user=user)
		):
			continue
		menu.append({"key": key, "label": _(label), "kind": kind, "target": target})
	return menu


@frappe.whitelist()
def get_counts() -> dict:
	"""The shell's counts: unread notifications and the tasks waiting now."""
	from smart_power.notify import unread
	from smart_power.sp_core.inbox import open_count

	return {"notifications": unread(frappe.session.user), "tasks": open_count()}
