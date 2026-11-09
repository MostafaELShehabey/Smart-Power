# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SPListValue(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		code: DF.Data
		is_active: DF.Check
		list_name: DF.Literal[
			"System Type",
			"Financing Type",
			"Payment Method",
			"Expense Type",
			"Field Expense",
			"Simple Record Type",
			"Job Type",
			"Call Result",
			"Lost Reason",
			"Region",
			"Service Issue",
			"Site Stage",
			"Inverter Brand",
		]
		parent_value: DF.Link | None
		sort_order: DF.Int
		value_ar: DF.Data
		value_en: DF.Data | None
	# end: auto-generated types

	def validate(self):
		self.code = (self.code or "").strip().upper()
		duplicate = frappe.db.exists(
			"SP List Value",
			{"list_name": self.list_name, "code": self.code, "name": ("!=", self.name)},
		)
		if duplicate:
			frappe.throw(_("Code {0} already exists in the list {1}.").format(self.code, _(self.list_name)))
