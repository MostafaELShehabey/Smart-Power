"""field_entries.mine (SP-148): the light entries the user logged."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe


@endpoint(methods=("GET",))
def mine() -> list[dict]:
	from smart_power.sp_winch.field_page import entries

	return entries()
