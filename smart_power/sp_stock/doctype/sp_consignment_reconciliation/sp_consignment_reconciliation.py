# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SPConsignmentReconciliation(Document):
	"""The supplier's monthly statement against our container figures (SP-93). The rules are in
	smart_power.sp_stock.consignment_reconciliation."""

	def validate(self):
		from smart_power.sp_stock.consignment_reconciliation import validate_reconciliation

		validate_reconciliation(self)
