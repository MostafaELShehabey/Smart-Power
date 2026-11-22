# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SPChassisCalc(Document):
	def validate(self):
		from smart_power.sp_quotes.chassis_calc import apply

		apply(self)
