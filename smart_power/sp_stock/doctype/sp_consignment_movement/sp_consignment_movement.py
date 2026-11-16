# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_stock import consignment


class SPConsignmentMovement(Document):
	def validate(self):
		consignment.validate_movement(self)

	def on_submit(self):
		consignment.on_movement_submit(self)

	def on_cancel(self):
		consignment.on_movement_cancel(self)
