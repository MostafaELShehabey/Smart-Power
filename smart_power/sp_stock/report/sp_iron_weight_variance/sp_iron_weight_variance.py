"""Theoretical vs scale weight of chassis iron (SP-178), per factory and per PO."""

from frappe import _

from smart_power.sp_stock.iron_weight import variance

WIDE, NARROW = 180, 120  # sp-allow-number: column widths in pixels


def execute(filters=None):
	columns = [
		{
			"fieldname": "factory",
			"label": _("Factory"),
			"fieldtype": "Link",
			"options": "SP Chassis Factory",
			"width": WIDE,
		},
		{
			"fieldname": "purchase_order",
			"label": _("Purchase Order"),
			"fieldtype": "Link",
			"options": "Purchase Order",
			"width": WIDE,
		},
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": NARROW},
		{
			"fieldname": "theoretical_kg",
			"label": _("Theoretical Weight (kg)"),
			"fieldtype": "Float",
			"width": NARROW,
		},
		{"fieldname": "actual_kg", "label": _("Scale Weight (kg)"), "fieldtype": "Float", "width": NARROW},
		{"fieldname": "variance_kg", "label": _("Difference (kg)"), "fieldtype": "Float", "width": NARROW},
		{"fieldname": "variance_pct", "label": _("Difference %"), "fieldtype": "Percent", "width": NARROW},
		{"fieldname": "warning", "label": _("Warning"), "fieldtype": "Data", "width": NARROW},
	]
	return columns, variance(filters)
