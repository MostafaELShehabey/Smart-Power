# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_site import settings_files


class SPSettingsFile(Document):
	def before_insert(self):
		settings_files.before_insert(self)

	def validate(self):
		settings_files.validate(self)

	def after_insert(self):
		settings_files.after_insert(self)

	def on_trash(self):
		settings_files.on_trash(self)
