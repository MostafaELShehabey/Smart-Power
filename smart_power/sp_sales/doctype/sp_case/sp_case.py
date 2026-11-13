# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_sales import case


class SPCase(Document):
	def before_insert(self):
		case.record_first_owners(self)

	def validate(self):
		case.validate(self)

	def on_update(self):
		# a lost or reopened case moves its quotes to Lost and back (SP-54)
		before = self.get_doc_before_save()
		if before and before.status != self.status and case.LOST in (self.status, before.status):
			from smart_power.sp_sales.quotation import refresh_case_quotes

			refresh_case_quotes(self.name)
		# a taken (or reassigned) request: the pool tasks close, the quote creator keeps one (SP-48)
		if before and before.quote_creator != self.quote_creator and self.quote_creator:
			from smart_power.sp_sales.quote_request import hand_over_request

			hand_over_request(self)
