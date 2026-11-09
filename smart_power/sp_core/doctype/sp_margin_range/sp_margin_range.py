# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class SPMarginRange(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		max_pct: DF.Percent
		min_pct: DF.Percent
		offer_type: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		scope: DF.Literal["", "Supply and install", "Supply only"]
	# end: auto-generated types

	pass
