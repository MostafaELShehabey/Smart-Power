# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SPAutomation(Document):
	def validate(self):
		from smart_power.sp_core.automation import validate_automation

		validate_automation(self)

	def on_update(self):
		from smart_power.sp_core.automation import clear_cache

		clear_cache()

	def on_trash(self):
		from smart_power.sp_core.automation import clear_cache

		clear_cache()
