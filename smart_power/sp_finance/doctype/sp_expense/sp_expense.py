# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

"""A10 Expense (SP-123): a direct expense, not from a custody. It posts on submit through the
Account Map (event Expense); the rules are in smart_power.sp_finance.expenses."""

from smart_power.sp_core.dated import SPDatedDocument


class SPExpense(SPDatedDocument):  # work date vs entry time (SP-44)
	def validate(self):
		from smart_power.sp_finance import expenses

		expenses.validate(self)

	def on_submit(self):
		from smart_power.sp_finance import expenses

		expenses.on_submit(self)
