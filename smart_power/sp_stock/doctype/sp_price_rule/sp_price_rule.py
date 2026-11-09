# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class SPPriceRule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		add_amount: DF.Currency
		adjust_pct: DF.Float
		base: DF.Literal["List Price", "P1 Cost", "BTC"]
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		target: DF.Literal["P1 Cost", "BTB", "BTC"]
	# end: auto-generated types

	pass
