# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_winch import bookings


class SPVehicleBooking(Document):
	def validate(self):
		bookings.validate(self)

	def on_update(self):
		bookings.on_update(self)
