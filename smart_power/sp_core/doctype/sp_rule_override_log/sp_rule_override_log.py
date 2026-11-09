# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from smart_power.sp_core.services.audit import prevent_change, prevent_delete


class SPRuleOverrideLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		message: DF.SmallText | None
		reason: DF.SmallText
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		rule: DF.Link | None
		rule_key: DF.Data | None
		user: DF.Link | None
	# end: auto-generated types

	def validate(self):
		prevent_change(self)

	def on_trash(self):
		prevent_delete(self)
