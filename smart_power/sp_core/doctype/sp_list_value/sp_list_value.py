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
		if self.parent_value == self.name:
			frappe.throw(_("A value cannot be its own parent."))

	def on_trash(self):
		"""A value in use is never deleted: the admin deactivates it instead (SP-32)."""
		from frappe.model.delete_doc import get_dynamic_linked_docs, get_linked_docs

		used_by = get_linked_docs(self) or get_dynamic_linked_docs(self)
		if used_by:
			first = used_by[0]
			frappe.throw(
				_(
					"{0} is used by {1} {2}, so it cannot be deleted. Untick Active to hide it from pickers instead."
				).format(
					frappe.bold(self.value_ar),
					_(first["reference_doctype"]),
					frappe.bold(first["reference_docname"]),
				),
				frappe.LinkExistsError,
				title=_("Deactivate instead"),
			)


def clean_code(code: str | None) -> str:
	"""Codes are upper case with no spaces: " cash box " → "CASH_BOX"."""
	return "_".join((code or "").upper().split())
