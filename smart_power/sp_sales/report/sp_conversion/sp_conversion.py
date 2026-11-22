"""R6 Conversion (SP-144): requests, quotes sent and won, by channel or person; lost reasons."""

from frappe import _

from smart_power.sp_sales.conversion import REASON, chart, rows

COUNT, RATE, NAME = 100, 110, 200  # sp-allow-number: column widths in pixels


def execute(filters: dict | None = None):
	filters = filters or {}
	data = rows(filters)
	return columns(filters.get("group_by")), data, None, chart(data, filters.get("group_by"))


def columns(group_by: str | None) -> list[dict]:
	head = {"fieldname": "group", "label": _(group_by or "Channel"), "fieldtype": "Data", "width": NAME}
	if group_by == REASON:
		return [
			head,
			{"fieldname": "lost", "label": _("Lost"), "fieldtype": "Int", "width": COUNT},
			{"fieldname": "share", "label": _("Share %"), "fieldtype": "Percent", "width": RATE},
		]
	return [
		head,
		{"fieldname": "requests", "label": _("Requests"), "fieldtype": "Int", "width": COUNT},
		{"fieldname": "quoted", "label": _("Quoted"), "fieldtype": "Int", "width": COUNT},
		{"fieldname": "won", "label": _("Won"), "fieldtype": "Int", "width": COUNT},
		{"fieldname": "lost", "label": _("Lost"), "fieldtype": "Int", "width": COUNT},
		{"fieldname": "win_rate", "label": _("Win Rate %"), "fieldtype": "Percent", "width": RATE},
		{"fieldname": "quote_rate", "label": _("Quoted %"), "fieldtype": "Percent", "width": RATE},
		{
			"fieldname": "avg_hours",
			"label": _("Avg Hours to Quote"),
			"fieldtype": "Float",
			"precision": 1,
			"width": RATE,
		},
		{"fieldname": "in_24h", "label": _("Quoted in 24 h %"), "fieldtype": "Percent", "width": RATE},
	]
