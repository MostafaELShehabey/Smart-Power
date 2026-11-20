# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SPStockCount(Document):
	"""A count sheet for one location (SP-94). Its rules are in smart_power.sp_stock.stock_count."""

	def validate(self):
		from smart_power.sp_stock.stock_count import validate_count

		validate_count(self)
