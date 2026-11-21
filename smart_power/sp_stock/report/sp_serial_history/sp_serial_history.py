"""Lookup by serial (SP-179): a motor's or pump's full history, for service. The rows come from
smart_power.sp_stock.serials.history."""

from frappe import _

from smart_power.sp_stock.serials import history

DATE, WIDE, NAME = 100, 180, 260  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	rows = history((filters or {}).get("serial_no"))
	return columns(), rows


def columns() -> list[dict]:
	return [
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": DATE},
		{"fieldname": "event", "label": _("Event"), "fieldtype": "Data", "width": NAME},
		{"fieldname": "item", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": WIDE},
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Data", "width": WIDE},
		{"fieldname": "reference_doctype", "label": _("Reference Type"), "fieldtype": "Data", "hidden": 1},
		{
			"fieldname": "reference_name",
			"label": _("Reference"),
			"fieldtype": "Dynamic Link",
			"options": "reference_doctype",
			"width": WIDE,
		},
		{"fieldname": "photo", "label": _("Nameplate Photo"), "fieldtype": "Data", "width": WIDE},
	]
