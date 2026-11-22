# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_finance import opening


class SPOpeningBalance(Document):
	def autoname(self):
		self.name = opening.name_for(self.company)

	def validate(self):
		opening.validate(self)

	def on_trash(self):
		opening.on_trash(self)
