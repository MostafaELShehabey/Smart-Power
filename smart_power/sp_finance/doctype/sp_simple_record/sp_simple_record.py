"""G7 Simple record (SP-43): a one-step record for anything without its own screen (a storage fee,
a small income, a one-off expense). When money moved it posts a simple Journal Entry
(smart_power.sp_finance.simple_record)."""

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SPSimpleRecord(Document):
	def validate(self):
		from smart_power.sp_finance import simple_record

		self.entry_time = self.entry_time or now_datetime()
		simple_record.validate(self)

	def on_submit(self):
		from smart_power.sp_finance import simple_record

		simple_record.post_record(self)
