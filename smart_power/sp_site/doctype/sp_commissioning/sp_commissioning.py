# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_site import commissioning


class SPCommissioning(Document):
	def validate(self):
		commissioning.validate(self)

	def before_submit(self):
		commissioning.before_submit(self)

	def on_submit(self):
		commissioning.on_submit(self)

	def before_cancel(self):
		commissioning.before_cancel(self)

	def on_cancel(self):
		commissioning.on_cancel(self)
