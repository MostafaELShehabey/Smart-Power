# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

"""SH2 Cash box day (SP-104): the rules are in smart_power.sp_finance.cash_box."""

from frappe.model.document import Document


class SPCashBoxDay(Document):
	def validate(self):
		from smart_power.sp_finance import cash_box

		cash_box.validate(self)

	def onload(self):
		from smart_power.sp_finance import cash_box

		if self.status == cash_box.OPEN and self.cash_account and self.day:
			cash_box.compute(self)  # an open day shows its figures as of now, not of its last save (BUG-15)
		self.set_onload("sp_cash_box", cash_box.state(self))
