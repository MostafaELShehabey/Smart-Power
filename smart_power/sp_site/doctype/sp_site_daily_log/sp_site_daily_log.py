# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_site import site_log


class SPSiteDailyLog(Document):
	def validate(self):
		site_log.validate(self)

	def on_submit(self):
		site_log.on_submit(self)

	def before_cancel(self):
		site_log.before_cancel(self)

	def on_cancel(self):
		site_log.on_cancel(self)
