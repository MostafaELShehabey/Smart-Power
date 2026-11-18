"""SP-84: goods are received on a draft Purchase Receipt, so the separate DocTypes go, and the cost
roles alone read the prices on a receipt."""

import frappe


def execute():
	from smart_power.permissions import sync_cost_permissions

	for doctype in ("SP Goods Receipt", "SP GR Line"):
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True, ignore_on_trash=True)
	frappe.db.sql_ddl("drop table if exists `tabSP Goods Receipt`")
	frappe.db.sql_ddl("drop table if exists `tabSP GR Line`")
	sync_cost_permissions()
