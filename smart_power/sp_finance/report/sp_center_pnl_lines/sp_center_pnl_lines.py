"""R4 Center P&L drill-down (SP-142): the GL lines behind one cell of the Center P&L."""

from frappe import _

from smart_power.sp_finance.center_pnl import lines

MONEY, NAME, DATE = 130, 180, 100  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	return columns(), lines(filters)


def columns() -> list[dict]:
	return [
		{"fieldname": "posting_date", "label": _("Posting Date"), "fieldtype": "Date", "width": DATE},
		{"fieldname": "voucher_type", "label": _("Voucher Type"), "fieldtype": "Data", "width": MONEY},
		{
			"fieldname": "voucher_no",
			"label": _("Voucher"),
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": NAME,
		},
		{"fieldname": "kind", "label": _("Kind"), "fieldtype": "Data", "width": MONEY},
		{
			"fieldname": "account",
			"label": _("Account"),
			"fieldtype": "Link",
			"options": "Account",
			"width": NAME,
		},
		{"fieldname": "center", "label": _("Center"), "fieldtype": "Data", "width": MONEY},
		{
			"fieldname": "cost_center",
			"label": _("Cost Center"),
			"fieldtype": "Link",
			"options": "Cost Center",
			"width": NAME,
		},
		{
			"fieldname": "station",
			"label": _("Station"),
			"fieldtype": "Link",
			"options": "SP Station",
			"width": MONEY,
		},
		{"fieldname": "event", "label": _("Posting Event"), "fieldtype": "Data", "width": MONEY},
		{"fieldname": "internal", "label": _("Internal Charge"), "fieldtype": "Check", "width": DATE},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": MONEY},
		{"fieldname": "remarks", "label": _("Remarks"), "fieldtype": "Small Text", "width": NAME},
	]
