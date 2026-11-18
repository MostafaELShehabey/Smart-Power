# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_stock import goods_receipt


class SPGoodsReceipt(Document):
	def validate(self):
		goods_receipt.validate(self)

	def after_insert(self):
		goods_receipt.after_insert(self)
