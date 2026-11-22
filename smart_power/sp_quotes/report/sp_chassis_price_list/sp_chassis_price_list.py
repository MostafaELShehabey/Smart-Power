"""The showroom's chassis price list (SP-166): one piece of each part, at the factory's prices."""

from frappe import _

from smart_power.sp_quotes.chassis_calc import price_list

WIDE, NARROW = 320, 120  # sp-allow-number: column widths in pixels
LENGTH_PRECISION = 2  # sp-allow-number: metres to the centimetre


def execute(filters=None):
	filters = filters or {}
	columns = [
		{"fieldname": "part", "label": _("Part"), "fieldtype": "Data", "width": WIDE},
		{"fieldname": "section", "label": _("Iron Section"), "fieldtype": "Data", "width": NARROW},
		{
			"fieldname": "length_m",
			"label": _("Length (m)"),
			"fieldtype": "Float",
			"precision": LENGTH_PRECISION,
			"width": NARROW,
		},
		{"fieldname": "rate", "label": _("Sale Price"), "fieldtype": "Currency", "width": NARROW},
	]
	if not filters.get("factory"):
		return columns, []
	return columns, price_list(filters["factory"])
