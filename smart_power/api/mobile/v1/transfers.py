"""transfers.mine (SP-148): the transfers the user recorded."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe


@endpoint(methods=("GET",))
def mine() -> list[dict]:
	return frappe.get_list(
		"SP Transfer",
		filters={"recorded_by": frappe.session.user},
		fields=[
			"name",
			"status",
			"work_date",
			"from_account",
			"to_account",
			"amount",
			"reject_reason",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=100,
	)
