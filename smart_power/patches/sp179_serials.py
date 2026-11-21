"""SP-179: motors and pumps by serial, the nameplate photos and the warranty register."""

import frappe


def execute():
	from frappe.utils.fixtures import sync_fixtures

	from smart_power.sp_site.commissioning import warranty_end
	from smart_power.sp_stock.serials import seed_serial_groups
	from smart_power.sp_stock.warranty import register_commissioning

	frappe.reload_doc("sp_stock", "doctype", "sp_warranty")
	frappe.reload_doc("sp_stock", "doctype", "sp_serial_photo")
	frappe.reload_doc("sp_site", "doctype", "sp_station_component")
	sync_fixtures("smart_power")  # the Serial Numbers flag on the Item Group, synced after patches
	seed_serial_groups()
	# the cover now ends on the same date (owner, 2026-11-22), and every commissioning joins the register
	for name in frappe.get_all("SP Commissioning", {"docstatus": 1}, pluck="name"):
		doc = frappe.get_doc("SP Commissioning", name)
		station = frappe.db.get_value("SP Station", doc.station, ["status", "operation_date"], as_dict=True)
		closed = station.status in ("Technically closed", "Financially closed")
		start = station.operation_date if closed and station.operation_date else doc.operation_date
		for row in doc.components:
			frappe.db.set_value(
				row.doctype,
				row.name,
				"warranty_end",
				warranty_end(start, row.warranty_months),
				update_modified=False,
			)
		register_commissioning(frappe.get_doc("SP Commissioning", name), start)
