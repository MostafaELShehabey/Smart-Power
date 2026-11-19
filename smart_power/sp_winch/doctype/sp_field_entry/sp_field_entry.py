# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from smart_power.sp_core.dated import SPDatedDocument
from smart_power.sp_winch import field_entry


class SPFieldEntry(SPDatedDocument):  # work date vs entry time (SP-44)
	def validate(self):
		field_entry.validate(self)

	def on_update(self):
		field_entry.on_update(self)
