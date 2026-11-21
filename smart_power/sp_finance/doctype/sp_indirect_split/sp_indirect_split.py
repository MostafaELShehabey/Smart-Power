# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

"""A16 Indirect cost split (SP-124): the rules are in smart_power.sp_finance.indirect_split."""

from frappe.model.document import Document


class SPIndirectSplit(Document):
	def validate(self):
		from smart_power.sp_finance import indirect_split

		indirect_split.validate(self)

	def on_submit(self):
		from smart_power.sp_finance import indirect_split

		indirect_split.on_submit(self)
