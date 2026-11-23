# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_stations import compliance


class SPComplianceDocument(Document):
	def validate(self):
		compliance.validate_document(self)
