# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_core import cutover


class SPCutover(Document):
	def before_insert(self):
		cutover.before_insert(self)

	def validate(self):
		cutover.validate(self)

	def on_update(self):
		cutover.on_update(self)
