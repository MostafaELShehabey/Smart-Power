"""review.field_entries (SP-148): the light entries waiting for their reviewer, flagged first."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe


@endpoint(methods=("GET",))
def field_entries() -> list[dict]:
	return frappe.get_list(
		"SP Field Entry",
		filters={"status": ("in", ("Logged", "Flagged"))},
		fields=["name", "entry_kind", "vehicle", "work_date", "status", "amount", "logged_by"],
		order_by="status desc, work_date desc",
		limit_page_length=100,
	)
