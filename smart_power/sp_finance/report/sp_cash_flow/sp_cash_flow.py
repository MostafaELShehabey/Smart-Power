"""R2 Cash flow (SP-140): the official balances, the collections and cheques due, and the supplier
dues, by week or month, with the running balance and its chart."""

from frappe import _

from smart_power.sp_finance.cash_flow import chart, rows

MONEY, NAME, DATE = 130, 120, 100  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	data = rows(filters)
	return columns(), data, None, chart(data)


def columns() -> list[dict]:
	money = [
		("opening", "Opening Balance"),
		("installments", "Instalments Due"),
		("cheques", "Cheques Due"),
		("inflow", "Total In"),
		("supplier_dues", "Supplier Dues"),
		("net", "Net"),
		("closing", "Closing Balance"),
	]
	return [
		{"fieldname": "period", "label": _("Period"), "fieldtype": "Data", "width": NAME},
		{"fieldname": "from_date", "label": _("From Date"), "fieldtype": "Date", "width": DATE},
		{"fieldname": "to_date", "label": _("To Date"), "fieldtype": "Date", "width": DATE},
		*({"fieldname": f, "label": _(label), "fieldtype": "Currency", "width": MONEY} for f, label in money),
	]
