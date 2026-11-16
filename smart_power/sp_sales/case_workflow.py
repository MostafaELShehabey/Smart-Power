"""The "SP Case" workflow (SP-46): its states and actions.

The workflow itself ships as a fixture (fixtures/workflow.json) so the admin can later change
it in X5 (SP-133) without a developer. Frappe needs its states and actions to exist before the
fixture loads, so `ensure_workflow_masters` runs on install and in a patch, both before
fixtures sync.
"""

import frappe

WORKFLOW = "SP Case"
# state → indicator style
STATES = {
	"Quote request": "Warning",
	"Draft": "Info",
	"Sent to customer": "Primary",
	"Follow-up": "Primary",
	"Won": "Success",
	"Lost": "Danger",
}
ACTIONS = (
	"Take Request",
	"Send to Customer",
	"Start Follow-up",
	"Request Revision",
	"Mark Won",
	"Mark Lost",
	"Reopen",
	"Price Check Only",  # SP-49: an enquiry closed at once as lost, reason "Price check only"
)


def ensure_workflow_masters() -> None:
	"""Create the workflow states and actions that are missing (admin changes are kept)."""
	for state, style in STATES.items():
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state, "style": style}
			).insert(ignore_permissions=True)
	for action in ACTIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)
