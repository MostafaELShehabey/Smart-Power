# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_site import service


class SPServiceTicket(Document):
	def validate(self):
		service.validate(self)

	def after_insert(self):
		service.after_insert(self)
