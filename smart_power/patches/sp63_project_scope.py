"""SP-63: the existing quotes are Supply and install (the scope their margin range is read for)."""

import frappe


def execute():
	from frappe.utils.fixtures import sync_fixtures

	sync_fixtures("smart_power")  # the new field comes with the fixtures, synced after patches
	frappe.db.sql(
		"update `tabQuotation` set sp_scope = %s where ifnull(sp_scope, '') = ''", "Supply and install"
	)
