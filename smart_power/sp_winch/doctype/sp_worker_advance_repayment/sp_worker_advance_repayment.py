# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SPWorkerAdvanceRepayment(Document):
	"""One repayment of a worker advance, by salary deduction or in cash (SP-181)."""
