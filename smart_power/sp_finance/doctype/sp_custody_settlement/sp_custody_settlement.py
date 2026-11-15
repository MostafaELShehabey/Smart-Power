# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_finance import custody


class SPCustodySettlement(Document):
	def validate(self):
		custody.validate_settlement(self)

	def on_submit(self):
		custody.on_settlement_submit(self)

	def on_cancel(self):
		custody.on_settlement_cancel(self)
