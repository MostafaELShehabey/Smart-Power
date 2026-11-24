"""forms.schema (SP-148): a form's simple fields, the admin's cx_ fields (X3) included, so they
show on the phone after the next sync."""

import frappe

from smart_power.api.mobile.v1.common import endpoint, is_money

SIMPLE = (
	"Data",
	"Small Text",
	"Text",
	"Int",
	"Float",
	"Currency",
	"Date",
	"Datetime",
	"Check",
	"Select",
	"Link",
	"Attach",
	"Attach Image",
)


@endpoint(methods=("GET",))
def schema(doctype: str) -> dict:
	frappe.has_permission(doctype, "read", throw=True)
	meta = frappe.get_meta(doctype)
	levels = set(meta.get_permlevel_access("read"))
	fields = []
	for df in meta.fields:
		if df.fieldtype not in SIMPLE or df.hidden or (df.permlevel or 0) not in levels | {0}:
			continue
		if df.permlevel and df.permlevel not in levels:
			continue
		if df.fieldtype == "Currency" and is_money(df.fieldname) and df.permlevel:
			continue
		fields.append(
			{
				"fieldname": df.fieldname,
				"label": frappe._(df.label or df.fieldname),
				"fieldtype": df.fieldtype,
				"options": df.options,
				"reqd": df.reqd,
				"depends_on": df.depends_on,
				"mandatory_depends_on": df.mandatory_depends_on,
				"link_filters": df.get("link_filters"),
				"custom": int(bool(df.get("is_custom_field"))),
			}
		)
	return {"doctype": doctype, "fields": fields}
