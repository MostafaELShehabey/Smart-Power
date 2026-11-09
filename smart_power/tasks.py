"""Scheduled jobs. Every threshold they use is read from settings, never written here."""

import frappe
from frappe.utils import add_days, now_datetime

STATS_WINDOW_DAYS = 30  # sp-allow-number: the X6 screen shows "fired in the last 30 days" (field label)


def update_rule_stats() -> None:
	"""Daily: refresh how often each rule fired in the stats window (SP-128, X6)."""
	since = add_days(now_datetime(), -STATS_WINDOW_DAYS)
	counts = dict(
		frappe.db.sql(
			"""select rule_key, count(*) from `tabSP Rule Hit` where hit_at >= %s group by rule_key""",
			since,
		)
	)
	for name in frappe.get_all("SP Rule Setting", pluck="name"):
		frappe.db.set_value("SP Rule Setting", name, "fired_30d", counts.get(name, 0), update_modified=False)


def backup_admin_customizations() -> None:
	from smart_power.devtools.fixtures import backup_admin_customizations as run

	run()
