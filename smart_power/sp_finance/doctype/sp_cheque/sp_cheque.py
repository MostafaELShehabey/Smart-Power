# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_finance import cheques


class SPCheque(Document):
	def validate(self):
		cheques.validate(self)
