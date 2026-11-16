"""A saved view of a list (SP-45): a tab with its filters, shown to the roles named."""

import json

import frappe
from frappe import _
from frappe.model.document import Document

FILTER_PARTS = 3  # sp-allow-number: [field, operator, value]


class SPListView(Document):
	def validate(self):
		if self.filters:
			try:
				rows = json.loads(self.filters)
			except ValueError:
				frappe.throw(_("The filters are not valid JSON."))
			if not isinstance(rows, list) or not all(
				isinstance(r, list) and len(r) == FILTER_PARTS for r in rows
			):
				frappe.throw(_("Filters are a list of [field, operator, value]."))
