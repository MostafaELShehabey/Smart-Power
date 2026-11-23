"""custody.mine (SP-148): the user's custody, its lines and what is left."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe


@endpoint(methods=("GET",))
def mine() -> dict:
	from smart_power.sp_finance.custody import my_custody

	return my_custody()
