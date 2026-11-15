"""SP-26: SP-114's interim "Receives Customer Money" flag on Account becomes Money Kind
(sp_account_kind: Official / Transit / Custody / Other). Runs before fixtures sync: the values
are kept, the new field is made first, the old one removed."""

import frappe


def execute():
	old = "Account-sp_receiving_kind"
	if not frappe.db.exists("Custom Field", old):
		return
	if not frappe.db.has_column("Account", "sp_account_kind"):
		from frappe.custom.doctype.custom_field.custom_field import create_custom_field

		create_custom_field(
			"Account",
			{
				"fieldname": "sp_account_kind",
				"fieldtype": "Select",
				"label": "Money Kind",
				"options": "\nOfficial\nTransit\nCustody\nOther",
				"insert_after": "account_type",
				"module": "SP Finance",
			},
		)
	if frappe.db.has_column("Account", "sp_receiving_kind"):
		frappe.db.sql(
			"update `tabAccount` set sp_account_kind = sp_receiving_kind where ifnull(sp_receiving_kind, '') != ''"
		)
	frappe.delete_doc("Custom Field", old, force=1, ignore_permissions=True)
