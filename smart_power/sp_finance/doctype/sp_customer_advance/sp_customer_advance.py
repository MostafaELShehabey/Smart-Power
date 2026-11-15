# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_finance import advances


class SPCustomerAdvance(Document):
	def validate(self):
		advances.validate(self)

	def on_submit(self):
		advances.on_submit(self)

	def on_cancel(self):
		advances.on_cancel(self)
