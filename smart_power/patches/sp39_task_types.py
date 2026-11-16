"""SP-39: open confirmation tasks take their own type (payment, transfer, settlement)."""

import frappe

TYPES = {
	"SP Customer Payment": "Payment to Confirm",
	"SP Transfer": "Transfer to Confirm",
	"SP Custody Settlement": "Settlement to Approve",
}


def execute():
	for doctype, task_type in TYPES.items():
		frappe.db.set_value(
			"SP Task",
			{"reference_doctype": doctype, "task_type": "Receipt to Confirm"},
			"task_type",
			task_type,
			update_modified=False,
		)
