"""R3 Installed capacity statement (SP-141), in the company's statement's column order."""

from frappe import _

from smart_power.sp_stations.installed_capacity import statement

DATE, NAME, KW, MONEY = 170, 200, 110, 130  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	return columns(), statement(filters or {})


def columns() -> list[dict]:
	return [
		{"fieldname": "operation_date", "label": _("Date"), "fieldtype": "Data", "width": DATE},
		{"fieldname": "station", "label": _("Station"), "fieldtype": "Data", "width": KW},
		{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": NAME},
		{"fieldname": "phone", "label": _("Phone Number"), "fieldtype": "Data", "width": KW},
		{"fieldname": "location", "label": _("Location"), "fieldtype": "Data", "width": NAME},
		{
			"fieldname": "capacity_kw",
			"label": _("Station Capacity (kW)"),
			"fieldtype": "Float",
			"precision": 1,
			"width": KW,
		},
		{"fieldname": "price_per_kw", "label": _("Price per kW"), "fieldtype": "Currency", "width": MONEY},
		{"fieldname": "total", "label": _("Total"), "fieldtype": "Currency", "width": MONEY},
	]
