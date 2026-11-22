# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_first_day, getdate

from smart_power.sp_finance import team_commission


class SPTeamCommission(Document):
	def autoname(self):
		abbr = frappe.get_cached_value("Company", self.company, "abbr")
		self.name = f"TC-{abbr}-{get_first_day(getdate(self.month)).strftime('%Y-%m')}"
		if frappe.db.exists(self.doctype, self.name):
			frappe.throw(
				frappe._("The team commission of this month is already entered in {0}.").format(self.name)
			)

	def validate(self):
		team_commission.validate(self)

	def on_update(self):
		team_commission.on_update(self)

	def on_trash(self):
		team_commission.on_trash(self)
