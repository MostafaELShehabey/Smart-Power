"""lookup.search (SP-148, M15): the global search."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe


@endpoint(methods=("GET",))
def search(q: str) -> dict:
	from smart_power.search import global_search

	return global_search(q)
