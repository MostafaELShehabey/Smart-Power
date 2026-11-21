# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SPChangeOrder(Document):
	"""S3 Change order (SP-78). The rules are in smart_power.sp_stations.change_order."""

	def validate(self):
		from smart_power.sp_stations.change_order import validate

		validate(self)

	def on_submit(self):
		from smart_power.sp_stations.change_order import on_submit

		on_submit(self)

	def before_cancel(self):
		from smart_power.sp_stations.change_order import before_cancel

		before_cancel(self)
