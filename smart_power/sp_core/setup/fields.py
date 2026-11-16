"""Custom fields a patch needs before the fixtures sync (patches run first on migrate)."""

import frappe


def ensure_fixture_fields(doctype: str, fieldnames: tuple[str, ...]) -> None:
	"""Create the doctype's custom fields from fixtures/custom_field.json where still missing."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	missing = [f for f in fieldnames if not frappe.db.has_column(doctype, f)]
	if not missing:
		return
	fixture = frappe.get_file_json(frappe.get_app_path("smart_power", "fixtures", "custom_field.json"))
	for row in fixture:
		if (
			row["dt"] == doctype
			and row["fieldname"] in missing
			and not frappe.db.exists("Custom Field", row["name"])
		):
			create_custom_field(doctype, {k: v for k, v in row.items() if k not in ("doctype", "name", "dt")})
