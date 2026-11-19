# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from smart_power.sp_core.dated import SPDatedDocument
from smart_power.sp_winch import crew_pay


class SPWorkerAdvance(SPDatedDocument):  # given on vs entry time (SP-44)
	def validate(self):
		crew_pay.validate_advance(self)

	def on_submit(self):
		crew_pay.submit_advance(self)

	def on_cancel(self):
		crew_pay.cancel_advance(self)
