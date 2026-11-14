# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_sales import followup


class SPCallLog(Document):
	def validate(self):
		followup.validate_call(self)

	def after_insert(self):
		followup.after_call(self)
