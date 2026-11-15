# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_stations import station


class SPStation(Document):
	def before_insert(self):
		station.before_insert(self)

	def after_insert(self):
		station.after_insert(self)

	def validate(self):
		station.validate(self)
