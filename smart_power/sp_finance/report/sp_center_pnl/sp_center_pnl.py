"""R4 Center P&L (SP-142): revenue, costs and profit per financial center, stations under Projects."""

from frappe import _

from smart_power.sp_finance.center_pnl import summary

MONEY, NAME, KEY = 130, 220, 0  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	return columns(), summary(filters)


def columns() -> list[dict]:
	money = [
		("revenue", "Revenue"),
		("cost", "Direct Cost"),
		("indirect", "Indirect Share"),
		("profit", "Profit"),
	]
	internal = [("internal_in", "Internal In"), ("internal_out", "Internal Out")]
	return [
		{"fieldname": "center", "label": _("Center"), "fieldtype": "Data", "width": NAME},
		{
			"fieldname": "station",
			"label": _("Station"),
			"fieldtype": "Link",
			"options": "SP Station",
			"width": NAME,
		},
		*({"fieldname": f, "label": _(label), "fieldtype": "Currency", "width": MONEY} for f, label in money),
		{"fieldname": "margin", "label": _("Margin %"), "fieldtype": "Percent", "width": MONEY},
		*(
			{"fieldname": f, "label": _(label), "fieldtype": "Currency", "width": MONEY}
			for f, label in internal
		),
		{"fieldname": "center_key", "label": _("Center"), "fieldtype": "Data", "hidden": 1, "width": KEY},
		{
			"fieldname": "no_station",
			"label": _("No station"),
			"fieldtype": "Check",
			"hidden": 1,
			"width": KEY,
		},
	]
