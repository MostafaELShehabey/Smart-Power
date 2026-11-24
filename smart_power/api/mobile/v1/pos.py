"""pos.expected_deliveries (SP-148): the goods the user's stores expect, without prices."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe


@endpoint(methods=("GET",))
def expected_deliveries() -> list[dict]:
	from smart_power.sp_stock.goods_receipt import expected_deliveries as rows

	return safe(rows())
