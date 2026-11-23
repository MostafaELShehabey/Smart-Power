"""X5 Workflows (SP-133): each record's lifecycle, and what the code needs kept in it.

    seed_workflows()        the SP workflows that are missing, from sp_core/setup/workflows.json;
                            a workflow the admin has is never touched again
    validate_workflow(doc)  Workflow validate: the guard below
    flows()                 the X5 list: every record's lifecycle
    diagram(key)            one record's states and transitions, with the locked ones

The owner's decisions (23-11-2026): the workflows are seeded once and the admin's version is kept
(they used to be fixtures, re-imported with force on every migrate); only the case and station
workflows are edited, in Frappe's Workflow Builder; the other records move through statuses the
code sets, so X5 shows them read-only; a new state goes before a locked state the system sets
(Follow-up → Waiting customer signature, then the deposit makes the case Won).

The guard (SP Workflow Guard in the story) is kept here with the code that reads those states:
    states     the code reads them: they cannot be removed or renamed
    by_system  only the system moves a record into them: no transition into them is added,
               and no new state follows them
    steps      transitions the code depends on: they cannot be removed
"""

import json
import os

import frappe
from frappe import _

from smart_power.sp_core.services.audit import audit

WORKFLOW = "Workflow"
SEED_FILE = "workflows.json"
GUARD = {
	"SP Case": {
		"states": ("Quote request", "Draft", "Sent to customer", "Follow-up", "Won", "Lost"),
		"by_system": ("Won",),  # the confirmed deposit (SP-175)
		"steps": (),
	},
	"SP Station": {
		"states": (
			"Open",
			"Purchasing",
			"Installing",
			"Technically closed",
			"Financially closed",
			"Cancelled",
		),
		"by_system": ("Cancelled",),  # the station cancel (SP-176)
		"steps": (("Technically closed", "Close Financially", "Financially closed"),),
	},
}
# the records whose statuses the code sets: shown read-only (label, doctype, status field)
READ_ONLY = (
	("Quote", "Quotation", "sp_status"),
	("Purchase Order", "Purchase Order", "status"),
	("Goods Receipt", "Purchase Receipt", "status"),
	("Transfer", "SP Transfer", "status"),
	("Customer Payment", "SP Customer Payment", "status"),
	("Cash Box Day", "SP Cash Box Day", "status"),
	("Cheque", "SP Cheque", "status"),
	("Custody", "SP Custody", "status"),
	("Custody Settlement", "SP Custody Settlement", "status"),
	("Field Entry", "SP Field Entry", "status"),
	("Consignment Container", "SP Consignment Container", "status"),
	("Journal Entry", "Journal Entry", "docstatus"),
)
EDITABLE = (("Case", "SP Case"), ("Station", "SP Station"))
DOCSTATUS = ("Draft", "Submitted", "Cancelled")
ADMIN_ROLES = ("SP Admin", "System Manager")


# --- seeding ------------------------------------------------------------------------------------------


def _seed() -> list[dict]:
	# a fixed file shipped inside the app, never a name from a request
	path = os.path.join(os.path.dirname(__file__), "setup", SEED_FILE)
	with open(path, encoding="utf-8") as f:  # nosemgrep
		return json.load(f)


def seed_workflows() -> list[str]:
	"""The SP workflows that do not exist yet. One the admin has is theirs from then on."""
	made = []
	for data in _seed():
		if frappe.db.exists(WORKFLOW, data["name"]):
			continue
		record = {k: v for k, v in data.items() if k not in ("modified", "creation", "owner", "modified_by")}
		doc = frappe.get_doc(record)
		doc.flags.sp_seed = True
		doc.insert(ignore_permissions=True)
		made.append(doc.name)
	return made


# --- the guard ----------------------------------------------------------------------------------------


def _core(state: str) -> str:
	return _("{0} is a core system state and cannot be removed or renamed.").format(_(state))


def validate_workflow(doc, method=None) -> None:
	"""Workflow validate: what the code needs stays; the code-driven records get no workflow."""
	read_only = {dt for _label, dt, _field in READ_ONLY}
	if doc.document_type in read_only and doc.is_active:
		frappe.throw(
			_("The statuses of {0} are set by the system; X5 shows them, but they have no workflow.").format(
				_(doc.document_type)
			),
			title=_("Locked workflow"),
		)
	guard = GUARD.get(doc.document_type)
	if not guard or doc.flags.sp_seed:
		return
	states = {s.state for s in doc.states}
	for state in guard["states"]:
		if state not in states:
			frappe.throw(_core(state), title=_("Locked workflow"))
	steps = {(t.state, t.action, t.next_state) for t in doc.transitions}
	for step in guard["steps"]:
		if step not in steps:
			frappe.throw(
				_("The step {0} → {1} ({2}) is needed by the system and cannot be removed.").format(
					_(step[0]), _(step[2]), _(step[1])
				),
				title=_("Locked workflow"),
			)
	before = doc.get_doc_before_save()
	known = {(t.state, t.action, t.next_state, t.allowed) for t in before.transitions} if before else set()
	locked = set(guard["states"])
	for t in doc.transitions:
		if (t.state, t.action, t.next_state, t.allowed) in known:
			continue
		if t.next_state in guard["by_system"] and t.state not in guard["by_system"]:
			frappe.throw(
				_("Only the system moves a record to {0}. Put the new step before it.").format(
					_(t.next_state)
				),
				title=_("Locked workflow"),
			)
		if t.state in guard["by_system"] and t.next_state not in locked:
			frappe.throw(
				_("{0} is set by the system: a new state goes before it, not after it.").format(_(t.state)),
				title=_("Locked workflow"),
			)


def sync_state_options(doc) -> list[str]:
	"""A new state becomes a choice of the record's status field (a Select), so records can take
	it; a removed one stays a choice, so the records already in it keep their status."""
	df = frappe.get_meta(doc.document_type).get_field(doc.workflow_state_field)
	if not df or df.fieldtype != "Select":
		return []
	options = [o for o in (df.options or "").split("\n") if o]
	missing = [s.state for s in doc.states if s.state not in options]
	if missing:
		frappe.make_property_setter(
			{
				"doctype": doc.document_type,
				"doctype_or_field": "DocField",
				"fieldname": doc.workflow_state_field,
				"property": "options",
				"value": "\n".join([*options, *missing]),
				"property_type": "Text",
			}
		)
		frappe.clear_cache(doctype=doc.document_type)
	return missing


def on_workflow_change(doc, method=None) -> None:
	"""Workflow on_update: new states become status choices, and the change is audited."""
	if doc.document_type in GUARD:
		sync_state_options(doc)
	if doc.document_type in GUARD and not doc.flags.sp_seed:
		audit(
			"Workflow changed",
			WORKFLOW,
			doc.name,
			states=[s.state for s in doc.states],
			transitions=[f"{t.state} → {t.action} → {t.next_state} ({t.allowed})" for t in doc.transitions],
		)


# --- X5 ----------------------------------------------------------------------------------------------


def _admin() -> None:
	frappe.only_for(ADMIN_ROLES)


@frappe.whitelist()
def flows() -> list[dict]:
	_admin()
	out = [{"key": dt, "label": _(label), "editable": True} for label, dt in EDITABLE]
	out += [{"key": dt, "label": _(label), "editable": False} for label, dt, _field in READ_ONLY]
	return [f for f in out if frappe.db.exists("DocType", f["key"])]


def _options(doctype: str, field: str) -> list[str]:
	if field == "docstatus":
		return list(DOCSTATUS)
	df = frappe.get_meta(doctype).get_field(field)
	return [o for o in ((df.options if df else "") or "").split("\n") if o]


@frappe.whitelist()
def diagram(key: str) -> dict:
	"""{states: [{state, label, locked, by_system, style}], transitions: [...], workflow, editable}"""
	_admin()
	if key in GUARD:
		guard = GUARD[key]
		name = frappe.db.get_value(WORKFLOW, {"document_type": key, "is_active": 1})
		wf = frappe.get_doc(WORKFLOW, name) if name else None
		states = [s.state for s in wf.states] if wf else list(guard["states"])
		styles = {
			r.name: r.style
			for r in frappe.get_all("Workflow State", {"name": ("in", states or [""])}, ["name", "style"])
		}
		steps = set(guard["steps"])
		transitions = {}
		for t in wf.transitions if wf else []:
			k = (t.state, t.action, t.next_state)
			row = transitions.setdefault(
				k,
				{
					"from": _(t.state),
					"action": _(t.action),
					"to": _(t.next_state),
					"roles": [],
					"locked": k in steps,
				},
			)
			row["roles"].append(_(t.allowed))
		return {
			"key": key,
			"label": _(key),
			"editable": True,
			"workflow": name,
			"states": [
				{
					"state": s,
					"label": _(s),
					"locked": s in guard["states"],
					"by_system": s in guard["by_system"],
					"style": styles.get(s),
				}
				for s in states
			],
			"transitions": list(transitions.values()),
		}
	spec = next((r for r in READ_ONLY if r[1] == key), None)
	if not spec:
		frappe.throw(_("{0} has no lifecycle in X5.").format(key))
	return {
		"key": key,
		"label": _(spec[0]),
		"editable": False,
		"workflow": None,
		"states": [
			{"state": s, "label": _(s), "locked": True, "by_system": True, "style": None}
			for s in _options(key, spec[2])
		],
		"transitions": [],
	}
