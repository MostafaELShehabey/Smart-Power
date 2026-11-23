# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SPFieldRule(Document):
	def on_update(self):
		from smart_power.sp_core.form_designer import clear_rules

		clear_rules()

	def on_trash(self):
		from smart_power.sp_core.form_designer import clear_rules

		clear_rules()
