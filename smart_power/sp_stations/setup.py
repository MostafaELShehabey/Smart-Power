"""Station setup (SP-175)."""

import frappe


def enable_stock_reservation() -> None:
	"""Stock is reserved against the Sales Order from the deposit (tech plan section 3 rule 8), so
	Stock Settings > Enable Stock Reservation is turned on, once (install and patch); partial
	reservations are allowed, since part of an order is often in stock. The admin may change it."""
	settings = frappe.get_single("Stock Settings")
	if settings.enable_stock_reservation:
		return
	settings.enable_stock_reservation = 1
	settings.allow_partial_reservation = 1
	settings.flags.ignore_mandatory = True
	settings.flags.ignore_permissions = True
	settings.save()


# S1 Stations list (SP-77): the story's column order; the title (customer) comes first and the
# station number last. "status_field" is the list's status column.
LIST_COLUMNS = (
	"systems_summary",
	"capacity_kw_total",
	"hp_total",
	"region",
	"financing_type",
	"status_field",
	"execution_owner",
	"collection_owner",
	"contract_date",
	"operation_date",
	"agreed_amount",
	"paid_amount",
	"remaining_amount",
	"next_due_date",
)


def seed_list_settings() -> None:
	"""The stations list's columns in the story's order, unless the admin has set the list up."""
	import json

	if frappe.db.exists("List View Settings", "SP Station"):
		return
	meta = frappe.get_meta("SP Station")
	fields = [
		{"fieldname": f, "label": meta.get_label(f) if f != "status_field" else "Status"}
		for f in LIST_COLUMNS
	]
	frappe.get_doc(
		{"doctype": "List View Settings", "name": "SP Station", "fields": json.dumps(fields)}
	).insert(ignore_permissions=True)
