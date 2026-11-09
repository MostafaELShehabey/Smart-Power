# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class SPAccountMap(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		center_rule: DF.Literal["From document", "Fixed"]
		cost_center: DF.Link | None
		credit_account: DF.Link | None
		debit_account: DF.Link | None
		event: DF.Literal["Field Job", "Custody", "Cheque", "Expense", "Refund", "Write-off"]
		note: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types

	pass
