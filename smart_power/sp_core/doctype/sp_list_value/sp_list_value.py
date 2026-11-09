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
		meta_json: DF.JSON | None
		parent_value: DF.Link | None
		sort_order: DF.Int
		value_ar: DF.Data
		value_en: DF.Data | None
	# end: auto-generated types

	def before_naming(self):
		# The name is "{list_name}-{code}", so the code is cleaned before it is named.
		self.code = clean_code(self.code)

	def validate(self):
		self.code = clean_code(self.code)
		filters = {"list_name": self.list_name, "code": self.code}
		if not self.is_new():
			filters["name"] = ("!=", self.name)
		duplicate = frappe.db.exists("SP List Value", filters)
		if duplicate:
			frappe.throw(_("Code {0} already exists in the list {1}.").format(self.code, _(self.list_name)))


def clean_code(code: str | None) -> str:
	"""Codes are upper case with no spaces: " cash box " → "CASH_BOX"."""
	return "_".join((code or "").upper().split())
