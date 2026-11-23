"""me.bootstrap (SP-148): what the app needs right after signing in."""

import frappe
from frappe.utils import now_datetime

from smart_power.api.mobile.v1.common import endpoint, touch_device


@endpoint(methods=("GET",))
def bootstrap() -> dict:
	from smart_power.dashboards.cards import get_home
	from smart_power.sp_finance.accounts import my_balances
	from smart_power.sp_winch.vehicles import driver_oil_note

	user = frappe.session.user
	doc = frappe.get_cached_doc("User", user)
	touch_device()
	return {
		"user": user,
		"full_name": doc.full_name,
		"language": doc.language or "ar",
		"roles": [r for r in frappe.get_roles(user) if r.startswith("SP ")],
		"tiles": get_home(),
		"settings": {
			"currency": frappe.db.get_default("currency"),
			"date_format": frappe.db.get_default("date_format"),
			"server_time": str(now_datetime()),
		},
		"balances": my_balances(),  # the user's own custody and transit, with the days held
		"oil": driver_oil_note(user),
	}
