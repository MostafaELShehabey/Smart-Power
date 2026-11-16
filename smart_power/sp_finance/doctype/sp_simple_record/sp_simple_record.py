"""G7 Simple record (SP-43): a one-step record for anything without its own screen (a storage fee,
a small income, a one-off expense). When money moved it posts a simple Journal Entry
(smart_power.sp_finance.simple_record). It is changed by Cancel and Amend with a reason: the old
entry is reversed by a new entry, never edited, and the new record posts its own."""

import frappe

from smart_power.sp_core.dated import SPDatedDocument


class SPSimpleRecord(SPDatedDocument):  # work date vs entry time (SP-44)
	def validate(self):
		from smart_power.sp_finance import simple_record

		simple_record.validate(self)

	def on_submit(self):
		from smart_power.sp_finance import simple_record

		simple_record.post_record(self)
		simple_record.log_change(self)

	def before_cancel(self):
		# its entry is reversed by a new entry, not cancelled (cancel_postings leaves it), so the
		# entry still pointing at the record must not stop the cancel
		self.flags.sp_keep_postings = True
		self.ignore_linked_doctypes = ("Journal Entry",)

	def on_cancel(self):
		from smart_power.sp_finance import simple_record

		simple_record.reverse_record(self)
