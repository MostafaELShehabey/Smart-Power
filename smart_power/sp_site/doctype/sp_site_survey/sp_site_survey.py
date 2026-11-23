# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_site import site_survey


class SPSiteSurvey(Document):
	def validate(self):
		site_survey.validate(self)
