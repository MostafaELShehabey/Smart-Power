"""The "SP Station" workflow (SP-73): its states and actions.

The workflow ships as a fixture (fixtures/workflow.json) so the admin can change it later in X5
without a developer. Frappe needs its states and actions before the fixture loads, so
`ensure_workflow_masters` runs on install and in a patch, both before fixtures sync.
"""

import frappe

WORKFLOW = "SP Station"
OPEN, PURCHASING, INSTALLING = "Open", "Purchasing", "Installing"
TECH_CLOSED, FIN_CLOSED, CANCELLED = "Technically closed", "Financially closed", "Cancelled"
# state → indicator style
STATES = {
	OPEN: "Info",
	PURCHASING: "Warning",
	INSTALLING: "Primary",
	TECH_CLOSED: "Success",
	FIN_CLOSED: "Success",
	CANCELLED: "Danger",
}
ACTIONS = (
	"Start Purchasing",
	"Start Installing",
	"Close Technically",
	"Close Financially",
	"Cancel Station",
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
