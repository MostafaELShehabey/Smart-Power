# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SPReviewItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		category: DF.Literal[
			"Rule Warning",
			"Margin",
			"Discount",
			"Override",
			"Edit",
			"Manual Entry",
			"Late Entry",
			"Abnormal",
			"Change Order",
			"Reassignment",
			"Consignment Conversion",
			"Write-off",
			"PO Sent",
		]
		comment: DF.SmallText | None
		highlight: DF.Check
		raised_by: DF.Link | None
		reason: DF.SmallText | None
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		reviewed_by: DF.Link | None
		reviewed_on: DF.Datetime | None
		rule: DF.Link | None
		status: DF.Literal["Open", "Reviewed"]
		summary: DF.SmallText | None
	# end: auto-generated types

	def validate(self):
		if self.status == "Reviewed" and not self.reviewed_by:
			self.reviewed_by = frappe.session.user
			self.reviewed_on = now_datetime()
		elif self.status == "Open":
			self.reviewed_by = None
			self.reviewed_on = None
