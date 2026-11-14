# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SPAccountMap(Document):
	"""One posting event's accounts, cost centers and project rule (SP-113). The admin edits the
	map in Smart Power Settings; smart_power.sp_finance.posting reads it."""
