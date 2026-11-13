"""Warehouses by location (SP-28, ERD 7.3).

Every warehouse in the stock ledger holds Smart Power's own stock, and its ERPNext
`warehouse_type` says where it is:

- Main: the main store
- Showroom: the showroom store
- Site: one per station, under the Sites group, linked to the station's Project
  (`sp_project`); made on the first transfer or receipt to that site
- Transit: goods on the way (ERPNext's own "Goods In Transit")

Supplier consignment (Africa System's panels) never enters a ledger warehouse: it is counted
by quantity on its containers (SP-91), so it cannot change company stock value. There is no
warehouse type for it on purpose.
"""

import frappe
from frappe import _

from smart_power.sp_core.setup.seed import defaults

MAIN, SHOWROOM, SITE, TRANSIT = "Main", "Showroom", "Site", "Transit"
SP_TYPES = (MAIN, SHOWROOM, SITE, TRANSIT)


def _spec() -> dict:
	return {k: v for k, v in defaults()["warehouses"].items() if not k.startswith("_")}


def seed_warehouse_types() -> None:
	for name in SP_TYPES:
		if not frappe.db.exists("Warehouse Type", name):
			frappe.get_doc({"doctype": "Warehouse Type", "name": name}).insert(ignore_permissions=True)


def seed_warehouses(company: str) -> None:
	"""The warehouse tree for a company: main store, showroom store, Sites group, transit.

	Existing warehouses are kept. ERPNext's default stores (Stores, Finished Goods, Work In
	Progress) are disabled while they are still empty, so nobody books stock into them, and
	the company's default warehouse becomes the main store.
	"""
	seed_warehouse_types()
	spec = _spec()
	root = frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 1, "parent_warehouse": ("is", "not set")}
	)
	if not root:
		return
	main = _ensure(spec["main"], company, root, warehouse_type=MAIN)
	_ensure(spec["showroom"], company, root, warehouse_type=SHOWROOM)
	_ensure(spec["sites"], company, root, is_group=1)
	transit = frappe.db.get_value("Company", company, "default_in_transit_warehouse") or frappe.db.get_value(
		"Warehouse", {"company": company, "warehouse_type": TRANSIT, "is_group": 0}
	)
	if transit:
		frappe.db.set_value("Warehouse", transit, "warehouse_type", TRANSIT)
	# ERPNext names them in the setup language, so match the English and the translated name
	for name in spec["disable_if_empty"]:
		warehouse = frappe.db.get_value(
			"Warehouse", {"warehouse_name": ("in", {name, _(name)}), "company": company, "is_group": 0}
		)
		if warehouse and not frappe.db.exists("Stock Ledger Entry", {"warehouse": warehouse}):
			frappe.db.set_value("Warehouse", warehouse, "disabled", 1)
	current = frappe.db.get_value("Company", company, "default_warehouse")
	if not current or frappe.db.get_value("Warehouse", current, "disabled"):
		frappe.db.set_value("Company", company, "default_warehouse", main)


def _ensure(warehouse_name: str, company: str, parent: str, warehouse_type=None, is_group=0) -> str:
	name = frappe.db.get_value("Warehouse", {"warehouse_name": warehouse_name, "company": company})
	if name:
		return name
	return (
		frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": warehouse_name,
				"company": company,
				"parent_warehouse": parent,
				"is_group": is_group,
				"warehouse_type": warehouse_type,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def warehouse_of(company: str, warehouse_type: str) -> str | None:
	"""The company's warehouse of a type (main, showroom, transit)."""
	return frappe.db.get_value(
		"Warehouse",
		{"company": company, "warehouse_type": warehouse_type, "is_group": 0, "disabled": 0},
		order_by="creation asc",
	)


def sites_group(company: str) -> str | None:
	return frappe.db.get_value(
		"Warehouse", {"company": company, "warehouse_name": _spec()["sites"], "is_group": 1}
	)


def site_warehouse(project: str, create: bool = True) -> str | None:
	"""The site warehouse of a station's Project; made on first use (first transfer or receipt)."""
	existing = frappe.db.get_value("Warehouse", {"sp_project": project, "warehouse_type": SITE})
	if existing or not create:
		return existing
	company, title = frappe.db.get_value("Project", project, ["company", "project_name"])
	parent = sites_group(company)
	if not parent:
		frappe.throw(
			_("Company {0} has no Sites warehouse group. Run the company setup first.").format(company)
		)
	doc = frappe.get_doc(
		{
			"doctype": "Warehouse",
			# named after the station only: it sits under the Sites group, and the name must not
			# depend on the language of whoever happened to trigger it
			"warehouse_name": title or project,
			"company": company,
			"parent_warehouse": parent,
			"warehouse_type": SITE,
			"sp_project": project,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def validate_warehouse(doc, method=None) -> None:
	"""Warehouse validate hook: a site warehouse belongs to exactly one station."""
	if doc.warehouse_type == SITE:
		if doc.is_group:
			frappe.throw(_("A site warehouse cannot be a group."))
		if not doc.get("sp_project"):
			frappe.throw(_("A site warehouse needs its station's project."))
		other = frappe.db.get_value(
			"Warehouse", {"sp_project": doc.sp_project, "warehouse_type": SITE, "name": ("!=", doc.name)}
		)
		if other:
			frappe.throw(_("Project {0} already has the site warehouse {1}.").format(doc.sp_project, other))
	elif doc.get("sp_project"):
		frappe.throw(_("Only a site warehouse is linked to a project."))
