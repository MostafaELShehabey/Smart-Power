# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_sales import case


class SPCase(Document):
	def before_insert(self):
		case.record_first_owners(self)

	def validate(self):
		case.validate(self)
