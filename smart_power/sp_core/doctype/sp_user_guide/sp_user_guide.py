# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_core import guides


class SPUserGuide(Document):
	def validate(self):
		guides.validate_guide(self)
