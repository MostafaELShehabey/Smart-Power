# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_stock import consignment


class SPConsignmentContainer(Document):
	def validate(self):
		consignment.validate_container(self)
