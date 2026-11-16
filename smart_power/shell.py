"""The app shell (SP-37): Smart Power's dock of module-group sidebars.

The groups are shipped as `Sidebar` documents (<module>/sidebar) on the app's `Dock`
(smart_power/dock). Frappe already drops a sidebar item the user cannot open, but ERPNext's base
roles read most masters (Item, Customer, Sales Order ...), so that alone would show almost every
group to almost everyone. A group is therefore shown only to the roles that work in it
(GROUP_ROLES), and a few items only to the roles that use them (ITEM_ROLES). This is navigation
only: what a user may open is still decided by the permissions.

    apply_to_boot(bootinfo)   boot_session: drop the groups and items this user does not work in
"""

import frappe

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
		"SP Main Store Keeper",
		"SP Showroom Store Keeper",
		"SP Site Receiver",
		"SP Purchase Officer",
		"SP Catalog Manager",
		"SP Project Manager",
		*ADMIN,
	),
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
	("Purchasing", "Purchase Orders"): ("SP Purchase Officer", "SP Supplier Accounts", *ADMIN),
	("Purchasing", "Suppliers"): ("SP Purchase Officer", "SP Supplier Accounts", *ADMIN),
	("Purchasing", "Consignment Containers"): ("SP Purchase Officer", "SP Main Store Keeper", *ADMIN),
	("Stations", "Contracts"): ("SP Contract Manager", "SP Project Manager", "SP Accountant", *ADMIN),
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
