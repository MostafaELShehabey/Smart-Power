# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_finance import transfer


class SPTransfer(Document):
	def validate(self):
		transfer.validate(self)

	def on_submit(self):
		transfer.on_submit(self)

	def on_cancel(self):
		transfer.on_cancel(self)
