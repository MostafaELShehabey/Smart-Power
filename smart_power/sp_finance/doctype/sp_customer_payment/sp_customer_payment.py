# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from smart_power.sp_core.dated import SPDatedDocument
from smart_power.sp_finance import customer_payment


class SPCustomerPayment(SPDatedDocument):  # work date vs entry time (SP-44)
	def validate(self):
		customer_payment.validate(self)

	def on_submit(self):
		customer_payment.on_submit(self)

	def on_cancel(self):
		customer_payment.on_cancel(self)
