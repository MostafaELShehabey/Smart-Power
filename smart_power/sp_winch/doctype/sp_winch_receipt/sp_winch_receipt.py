# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from smart_power.sp_core.dated import SPDatedDocument
from smart_power.sp_winch import receipts


class SPWinchReceipt(SPDatedDocument):  # received on vs entry time (SP-44)
	def validate(self):
		receipts.validate(self)

	def on_update(self):
		receipts.on_update(self)

	def on_trash(self):
		receipts.on_trash(self)
