"""SP-182: each System Type's request fields, kept so far only in its Extra Data, become the rows
of its Request Fields table (the save converts them)."""

import frappe

from smart_power.sp_sales.quote_request import LIST_VALUE, META_KEY, SYSTEM_TYPE_LIST, _meta


def execute():
	frappe.reload_doc("sp_core", "doctype", "sp_request_field")
	frappe.reload_doc("sp_core", "doctype", "sp_list_value")
	for name in frappe.get_all(LIST_VALUE, {"list_name": SYSTEM_TYPE_LIST}, pluck="name"):
		doc = frappe.get_doc(LIST_VALUE, name)
		if doc.get("request_fields") or not _meta(name).get(META_KEY):
			continue
		doc.flags.ignore_permissions = True
		doc.save()
