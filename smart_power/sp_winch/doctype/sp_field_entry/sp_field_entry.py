# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from smart_power.sp_core.dated import SPDatedDocument
from smart_power.sp_winch import field_entry, field_lock, receipts, review


class SPFieldEntry(SPDatedDocument):  # work date vs entry time (SP-44)
	def validate(self):
		field_entry.validate(self)
		receipts.validate_job(self)

	def before_save(self):
		field_lock.before_save(self)
		review.before_save(self)

	def after_insert(self):
		field_lock.after_insert(self)

	def on_update(self):
		field_entry.on_update(self)
		review.on_update(self)
		receipts.on_entry_update(self)
