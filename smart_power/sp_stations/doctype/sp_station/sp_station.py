# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import get_fullname

from smart_power.sp_stations import station


class SPStation(Document):
	def onload(self):
		from smart_power.sp_stations.reassign import scheduled

		self.set_onload("sp_scheduled_reassign", scheduled(self))  # SP-79
		# the owners' names for the form's owner line (a user's own boot may not know them)
		self.set_onload(
			"sp_owner_names",
			{
				u: get_fullname(u)
				for u in (self.sales_owner, self.execution_owner, self.collection_owner)
				if u
			},
		)

	def before_insert(self):
		station.before_insert(self)

	def after_insert(self):
		station.after_insert(self)

	def validate(self):
		station.validate(self)

	def on_update(self):
		from smart_power.sp_stations.commission import on_station_update

		on_station_update(self)  # the technical close may post the referrer commission (SP-177)
