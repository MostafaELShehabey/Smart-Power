"""X2 Permissions matrix (SP-131): the admin ticks who sees and does what, instead of editing
Frappe's Role Permissions Manager.

    roles()                  the roles the matrix shows
    load(role)               per menu group (SP Module Map) and document type: view, create, edit,
                             delete, confirm, export, own records, assigned to me; and the field rules
    save(role, doctypes, fields)  writes the changes and audits each one; returns them
    new_role(name), clone(source, name), preview(role)

The ticks are Frappe's own Role Permissions (Custom DocPerm, at permission level 0):

    view, create, edit, delete, export   read, create, write, delete, export
    confirm                              submit, and the document's workflow transitions
    own records                          if_owner ("only if creator")
    assigned to me                       an SP Role Row Rule (row_rules.py)

and the field rules are the higher permission levels: cost and profit (the quote's level 2, one
tick, owner's decision 23-11-2026), supplier prices (the purchase order and receipt's level 2),
station costs (the station's level 2). Until the sandbox (X11, SP-136) exists, a save is live:
the page lists every change for the admin to confirm, and each one goes to the audit log.
SP Admin and System Manager always keep their access: the matrix never changes them.
"""

import json
import os

import frappe
from frappe import _
from frappe.permissions import setup_custom_perms
from frappe.utils import cint

from smart_power.permissions import COST_PERMLEVEL
from smart_power.sp_core.row_rules import ASSIGNED, ASSIGNEE, RULE
from smart_power.sp_core.services.audit import audit

PERM, MAP = "Custom DocPerm", "SP Module Map"
ADMIN_ROLES = ("SP Admin", "System Manager")
PROTECTED = (*ADMIN_ROLES, "Administrator", "Guest", "All", "Desk User")
ACTIONS = {"view": "read", "create": "create", "edit": "write", "delete": "delete", "export": "export"}
WITH_VIEW = ("print", "email", "report", "share")  # follow view on a new row
# the hidden fields of each rule live at the cost permission level (permissions.py, SP-35, SP-76)
FIELD_RULES = {
	"cost_profit": (("Quotation", COST_PERMLEVEL),),
	"supplier_prices": (("Purchase Order", COST_PERMLEVEL), ("Purchase Receipt", COST_PERMLEVEL)),
	"station_costs": (("SP Station", COST_PERMLEVEL),),
}
FIELD_LABELS = {
	"cost_profit": "See cost and profit",
	"supplier_prices": "See supplier prices",
	"station_costs": "See station costs",
}
ALL, SOME, NONE = "all", "some", "none"


def _admin() -> None:
	frappe.only_for(ADMIN_ROLES)


def _editable(role: str) -> None:
	if role in PROTECTED:
		frappe.throw(_("{0} always keeps its access; the matrix does not change it.").format(role))
	if not frappe.db.exists("Role", role):
		frappe.throw(_("Role {0} does not exist.").format(role))


@frappe.whitelist()
def roles() -> list[dict]:
	_admin()
	rows = frappe.get_all(
		"Role",
		{"desk_access": 1, "disabled": 0, "name": ("not in", PROTECTED[2:])},
		pluck="name",
		order_by="name",
	)
	return [{"role": r, "label": _(r), "locked": r in ADMIN_ROLES} for r in rows]


# --- the module map -------------------------------------------------------------------------------


def _sidebar_files() -> list[str]:
	root = frappe.get_app_path("smart_power")
	out = []
	for module in sorted(os.listdir(root)):
		folder = os.path.join(root, module, "sidebar")
		if os.path.isdir(folder):
			for name in sorted(os.listdir(folder)):
				path = os.path.join(folder, name, f"{name}.json")
				if os.path.isfile(path):
					out.append(path)
	return out


def sidebars() -> dict[str, list[dict]]:
	"""{group: its sidebar items} from the app's own sidebar files."""
	out = {}
	for path in _sidebar_files():
		# the app's own sidebar files, never a path from a request
		with open(path, encoding="utf-8") as f:  # nosemgrep
			data = json.load(f)
		out[data["title"]] = data.get("items") or []
	return out


def seed_module_map() -> list[str]:
	"""A module map entry for each menu group that has none, with its sidebar's document types.
	An entry the admin has is never touched."""
	made = []
	for group, items in sidebars().items():
		doctypes = [
			i["link_to"]
			for i in items
			if i.get("link_type") == "DocType" and frappe.db.exists("DocType", i.get("link_to"))
		]
		if not doctypes or frappe.db.exists(MAP, group):
			continue
		frappe.get_doc(
			{"doctype": MAP, "module_name": group, "doctypes": [{"document_type": d} for d in doctypes]}
		).insert(ignore_permissions=True)
		made.append(group)
	return made


def module_map() -> list[tuple[str, list[str]]]:
	rows = frappe.get_all(
		"SP Module Map DocType", {"parenttype": MAP}, ["parent", "document_type"], order_by="parent, idx"
	)
	out = {}
	for row in rows:
		out.setdefault(row.parent, [])
		if row.document_type not in out[row.parent]:
			out[row.parent].append(row.document_type)
	order = list(sidebars())
	return sorted(out.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order))


# --- reading one role -------------------------------------------------------------------------------


def _level_rows(doctype: str, role: str, level: int = 0) -> list:
	return [p for p in frappe.get_meta(doctype).permissions if p.role == role and cint(p.permlevel) == level]


def _workflow(doctype: str):
	name = frappe.db.get_value("Workflow", {"document_type": doctype, "is_active": 1})
	return frappe.get_doc("Workflow", name) if name else None


def _steps(workflow) -> set:
	return {(t.state, t.action, t.next_state) for t in workflow.transitions}


def _confirm_state(doctype: str, role: str, row) -> str | None:
	meta = frappe.get_meta(doctype)
	parts = []
	if meta.is_submittable:
		parts.append(bool(row and row.submit))
	workflow = _workflow(doctype)
	if workflow:
		mine = {(t.state, t.action, t.next_state) for t in workflow.transitions if t.allowed == role}
		steps = _steps(workflow)
		parts.append(ALL if steps and mine >= steps else (SOME if mine else NONE))
	if not parts:
		return None
	values = [ALL if p is True else (NONE if p is False else p) for p in parts]
	if all(v == ALL for v in values):
		return ALL
	return NONE if all(v == NONE for v in values) else SOME


def _doctype_state(doctype: str, role: str) -> dict:
	rows = _level_rows(doctype, role)
	row = rows[0] if rows else None
	state = {key: bool(row and row.get(ptype)) for key, ptype in ACTIONS.items()}
	state["own"] = bool(row and row.if_owner)
	state["confirm"] = _confirm_state(doctype, role, row)
	state["assigned"] = (
		bool(frappe.db.exists(RULE, {"role": role, "document_type": doctype}))
		if doctype in ASSIGNEE
		else None
	)
	return state


def _field_state(role: str) -> dict:
	out = {}
	for key, levels in FIELD_RULES.items():
		given = [
			bool(_level_rows(dt, role, level)) for dt, level in levels if frappe.db.exists("DocType", dt)
		]
		out[key] = ALL if given and all(given) else (SOME if any(given) else NONE)
	return out


@frappe.whitelist()
def load(role: str) -> dict:
	_admin()
	modules = []
	for module, doctypes in module_map():
		modules.append(
			{
				"module": module,
				"label": _(module),
				"doctypes": [
					{"doctype": dt, "label": _(dt), **_doctype_state(dt, role)}
					for dt in doctypes
					if frappe.db.exists("DocType", dt)
				],
			}
		)
	return {
		"role": role,
		"locked": role in PROTECTED,
		"modules": modules,
		"fields": [
			{"key": k, "label": _(FIELD_LABELS[k]), "state": v} for k, v in _field_state(role).items()
		],
	}


# --- writing ------------------------------------------------------------------------------------------


def _row_name(doctype: str, role: str, level: int = 0) -> str | None:
	return frappe.db.get_value(
		PERM, {"parent": doctype, "role": role, "permlevel": level}, order_by="if_owner"
	)


def _set_row(doctype: str, role: str, level: int, values: dict) -> None:
	"""The role's row at the level, with the values; no row when nothing is given."""
	setup_custom_perms(doctype)
	name = _row_name(doctype, role, level)
	if not any(values.values()):
		if name:
			frappe.delete_doc(PERM, name, ignore_permissions=True)
			frappe.clear_cache(doctype=doctype)
		return
	if name:
		frappe.db.set_value(PERM, name, values)
	else:
		frappe.get_doc(
			{
				"doctype": PERM,
				"parent": doctype,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": level,
				**values,
			}
		).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=doctype)


def _set_confirm(doctype: str, role: str, on: bool) -> None:
	if frappe.get_meta(doctype).is_submittable:
		name = _row_name(doctype, role)
		if name:
			frappe.db.set_value(PERM, name, "submit", 1 if on else 0)
	workflow = _workflow(doctype)
	if not workflow:
		return
	mine = {(t.state, t.action, t.next_state) for t in workflow.transitions if t.allowed == role}
	if on:
		for t in list(workflow.transitions):
			key = (t.state, t.action, t.next_state)
			if key not in mine:
				copy = {
					f: t.get(f) for f in ("state", "action", "next_state", "allow_self_approval", "condition")
				}
				workflow.append("transitions", {**copy, "allowed": role})
				mine.add(key)
	else:
		workflow.transitions = [t for t in workflow.transitions if t.allowed != role]
	workflow.flags.ignore_permissions = True
	workflow.save()


def _set_assigned(doctype: str, role: str, on: bool) -> None:
	name = frappe.db.get_value(RULE, {"role": role, "document_type": doctype})
	if on and not name:
		frappe.get_doc({"doctype": RULE, "role": role, "document_type": doctype, "rule": ASSIGNED}).insert(
			ignore_permissions=True
		)
	elif not on and name:
		frappe.delete_doc(RULE, name, ignore_permissions=True)


def _apply_doctype(role: str, doctype: str, want: dict) -> list[str]:
	before = _doctype_state(doctype, role)
	changes = []
	actions = {k: bool(want.get(k, before[k])) for k in ACTIONS}
	own = bool(want.get("own", before["own"]))
	if any(actions[k] != before[k] for k in ACTIONS) or own != before["own"]:
		values = {ptype: cint(actions[k]) for k, ptype in ACTIONS.items()}
		values["if_owner"] = cint(own and actions["view"])
		if actions["view"] and not before["view"]:
			values.update(dict.fromkeys(WITH_VIEW, 1))
		if not actions["view"]:
			values = dict.fromkeys(values, 0)
		_set_row(doctype, role, 0, values)
		changes += [
			f"{doctype}: {k} → {'✓' if actions[k] else '✗'}" for k in ACTIONS if actions[k] != before[k]
		]
		if own != before["own"]:
			changes.append(f"{doctype}: own → {'✓' if own else '✗'}")
	confirm = want.get("confirm")
	if (
		before["confirm"] is not None
		and confirm is not None
		and (confirm == ALL) != (before["confirm"] == ALL)
	):
		if confirm == ALL and not actions["view"]:
			frappe.throw(_("{0}: give View before Confirm.").format(_(doctype)))
		_set_confirm(doctype, role, confirm == ALL)
		changes.append(f"{doctype}: confirm → {'✓' if confirm == ALL else '✗'}")
	assigned = want.get("assigned")
	if before["assigned"] is not None and assigned is not None and bool(assigned) != before["assigned"]:
		_set_assigned(doctype, role, bool(assigned))
		changes.append(f"{doctype}: assigned → {'✓' if assigned else '✗'}")
	return changes


def _apply_field(role: str, key: str, on: bool) -> list[str]:
	"""A field rule on the rule's document types the role may view (its level 0 row)."""
	changes = []
	doctypes = [(dt, level) for dt, level in FIELD_RULES[key] if frappe.db.exists("DocType", dt)]
	if on and not any(_level_rows(dt, role) for dt, _level in doctypes):
		names = ", ".join(_(dt) for dt, _level in doctypes)
		frappe.throw(_("{0}: give View on {1} first.").format(_(FIELD_LABELS[key]), names))
	for doctype, level in doctypes:
		has = bool(_level_rows(doctype, role, level))
		if has == on or (on and not _level_rows(doctype, role)):
			continue
		_set_row(doctype, role, level, {"read": cint(on)})
		changes.append(f"{doctype} level {level}: read → {'✓' if on else '✗'}")
	return changes


@frappe.whitelist(methods=["POST"])
def save(role: str, doctypes: dict | str | None = None, fields: dict | str | None = None) -> list[str]:
	"""Write the role's ticks: {doctype: {view, create, …}} and {field rule: bool}. Returns the
	changes made, each audited."""
	_admin()
	_editable(role)
	doctypes = frappe.parse_json(doctypes) if isinstance(doctypes, str) else doctypes or {}
	fields = frappe.parse_json(fields) if isinstance(fields, str) else fields or {}
	changes = []
	for doctype, want in doctypes.items():
		if frappe.db.exists("DocType", doctype):
			changes += _apply_doctype(role, doctype, want or {})
	for key, on in fields.items():
		if key in FIELD_RULES:
			changes += _apply_field(role, key, bool(on))
	if changes:
		audit("Permissions changed", "Role", role, changes=changes)
	return changes


@frappe.whitelist(methods=["POST"])
def new_role(name: str) -> str:
	_admin()
	name = (name or "").strip()
	if not name:
		frappe.throw(_("Enter the role's name."))
	if frappe.db.exists("Role", name):
		frappe.throw(_("Role {0} already exists.").format(name))
	# is_custom: the menu opens its groups from its permissions (shell.groups_for_roles)
	frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 1, "is_custom": 1}).insert(
		ignore_permissions=True
	)
	audit("Role created", "Role", name)
	return name


@frappe.whitelist(methods=["POST"])
def clone(source: str, name: str) -> dict:
	"""A new role with the source's Role Permissions, row rules and workflow steps."""
	_admin()
	if not frappe.db.exists("Role", source):
		frappe.throw(_("Role {0} does not exist.").format(source))
	name = new_role(name)
	standard = frappe.get_all("DocPerm", {"role": source}, pluck="parent", distinct=True)
	custom = frappe.get_all(PERM, {"role": source}, pluck="parent", distinct=True)
	for doctype in sorted(set(standard) | set(custom)):
		setup_custom_perms(doctype)
		for row in frappe.get_all(PERM, {"parent": doctype, "role": source}, ["*"]):
			copy = {
				k: v
				for k, v in row.items()
				if k not in ("name", "creation", "modified", "owner", "modified_by", "idx")
			}
			frappe.get_doc({**copy, "doctype": PERM, "role": name}).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=doctype)
	for rule in frappe.get_all(RULE, {"role": source}, ["document_type", "rule"]):
		frappe.get_doc({"doctype": RULE, "role": name, **rule}).insert(ignore_permissions=True)
	for wf in frappe.get_all(
		"Workflow Transition", {"allowed": source, "parenttype": "Workflow"}, pluck="parent", distinct=True
	):
		workflow = frappe.get_doc("Workflow", wf)
		for t in [t for t in workflow.transitions if t.allowed == source]:
			copy = {
				f: t.get(f) for f in ("state", "action", "next_state", "allow_self_approval", "condition")
			}
			workflow.append("transitions", {**copy, "allowed": name})
		workflow.flags.ignore_permissions = True
		workflow.save()
	rows = frappe.db.count(PERM, {"role": name})
	audit("Role cloned", "Role", name, source=source, permissions=rows)
	return {"role": name, "permissions": rows}


# --- preview --------------------------------------------------------------------------------------


@frappe.whitelist()
def preview(role: str) -> dict:
	"""The menu a user with only this role gets: the groups and their items, and "+ New"."""
	from smart_power.shell import groups_for_roles, new_actions_for_roles

	_admin()
	bars = sidebars()
	groups = []
	for group, hidden in groups_for_roles({role}).items():
		items = [
			_(i["label"])
			for i in bars.get(group, [])
			if i.get("type") == "Link" and i.get("label") not in hidden
		]
		groups.append({"group": _(group), "items": items})
	return {"role": role, "groups": groups, "new": new_actions_for_roles({role})}
