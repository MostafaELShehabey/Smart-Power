# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SPCompanySettings(Document):
	def validate(self):
		labels = [(row.label or "").strip() for row in self.addresses]
		for row, label in zip(self.addresses, labels, strict=True):
			if labels.count(label) > 1:
				frappe.throw(
					_("Row {0}: the address {1} is listed twice.").format(row.idx, frappe.bold(label))
				)
