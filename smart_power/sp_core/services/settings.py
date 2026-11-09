"""Read access to Smart Power Settings for business code.

Code never holds a business number; it asks for the setting (tech plan section 1).
"""

import frappe

from smart_power.constants import SETTINGS_DOCTYPE


def get_settings():
	"""The cached Smart Power Settings document (read-only use)."""
	return frappe.get_cached_doc(SETTINGS_DOCTYPE)


def get_value(fieldname: str, default=None):
	value = get_settings().get(fieldname)
	return default if value in (None, "") else value


def margin_range(offer_type: str | None, scope: str | None):
	"""The most specific margin row for an offer type and scope, or None.

	A row with an empty offer type or scope applies to all of them; a row that names both wins.
	"""
	matches = [
		row
		for row in get_settings().margin_ranges
		if (not row.offer_type or row.offer_type == offer_type) and (not row.scope or row.scope == scope)
	]
	# the offer type is more specific than the scope
	return max(matches, key=lambda row: (bool(row.offer_type), bool(row.scope)), default=None)


def brand_priority(item_group: str) -> list[str]:
	"""Brands for an item group in priority order (lowest number first)."""
	rows = [r for r in get_settings().brand_priorities if r.item_group == item_group]
	return [r.brand for r in sorted(rows, key=lambda r: r.priority or 0)]


def account_map(event: str):
	"""The Account Map row for a posting event, or None."""
	for row in get_settings().account_map:
		if row.event == event:
			return row
	return None
