# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_sales import campaigns


class SPCampaign(Document):
	def validate(self):
		campaigns.validate(self)

	def onload(self):
		self.set_onload("funnel", campaigns.funnel(self))
