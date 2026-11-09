"""Item search by words in any order (SP-29, I1).

ERPNext's item_query matches the typed text as one block, so "لوح 710" does not find
"لوح RISEN 710 وات". Here the text is split into words; an item matches when every word
appears in its code, name, Arabic name, brand, group or description. The matching names are
then passed to ERPNext's own item_query, so its filters (disabled items, variants, customer
and supplier items, company) and its result format stay the same.
"""

import re

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Coalesce

ERPNEXT_ITEM_QUERY = "erpnext.controllers.queries.item_query"
SEARCHED_FIELDS = ("name", "item_name", "sp_name_ar", "brand", "item_group", "description")
CANDIDATE_LIMIT = 500  # sp-allow-number: search result cap, not a business value
LIKE_WILDCARDS = re.compile(r"[%_\\]")


def split_words(txt: str | None) -> list[str]:
	"""The words of the search text, without LIKE wildcards."""
	return [w for w in (LIKE_WILDCARDS.sub(" ", txt or "")).split() if w]


def items_matching_all(words: list[str]) -> list[str]:
	"""Items where every word appears in at least one searched field."""
	item = DocType("Item")
	query = frappe.qb.from_(item).select(item.name).where(item.disabled == 0)
	for word in words:
		pattern = f"%{word}%"
		any_field = None
		for fieldname in SEARCHED_FIELDS:
			cond = Coalesce(item[fieldname], "").like(pattern)
			any_field = cond if any_field is None else any_field | cond
		query = query.where(any_field)
	return query.limit(CANDIDATE_LIMIT).run(pluck=True)


def with_name_filter(filters, names: list[str]):
	"""ERPNext's filters plus "name in names", in the same shape (dict or list)."""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	if isinstance(filters, list):
		return [*filters, ["Item", "name", "in", names]]
	return {**(filters or {}), "name": ["in", names]}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_query(
	doctype: str,
	txt: str,
	searchfield: str,
	start: int,
	page_len: int,
	filters: dict | list | str | None,
	as_dict: bool = False,
):
	"""ERPNext's item_query, with words matched in any order and any field."""
	from erpnext.controllers.queries import item_query as erpnext_item_query

	words = split_words(txt)
	if len(words) <= 1:
		return erpnext_item_query(doctype, txt, searchfield, start, page_len, filters, as_dict=as_dict)
	names = items_matching_all(words)
	if not names:
		return [] if as_dict else ()
	return erpnext_item_query(
		doctype, "", searchfield, start, page_len, with_name_filter(filters, names), as_dict=as_dict
	)
