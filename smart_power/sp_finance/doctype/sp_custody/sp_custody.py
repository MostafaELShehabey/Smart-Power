# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_finance import custody


class SPCustody(Document):
	def validate(self):
		custody.validate(self)

	def on_submit(self):
		custody.on_submit(self)

	def on_cancel(self):
		custody.on_cancel(self)
