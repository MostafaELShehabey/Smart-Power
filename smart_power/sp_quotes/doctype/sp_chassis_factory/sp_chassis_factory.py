# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SPChassisFactory(Document):
	def validate(self):
		from smart_power.sp_quotes.chassis_calc import validate_factory

		validate_factory(self)
