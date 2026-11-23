"""X3 Fields and forms (SP-132): the admin adds and changes fields on the SP forms without a
developer, through Frappe's own Customize Form (Custom Field and Property Setter rows).

    forms()                                  the forms the designer opens, and the system types
    load(doctype)                            the form's fields, in order, with their flags
    add_field(doctype, spec)                 a new field, its fieldname prefixed cx_
    change_field(doctype, fieldname, spec)   hide or show, required, move up or down, show only when
    new_list(name)                           a new list (X4), for list fields
    validate_required(doc)                   the "*" validate hook: a field required only when shown

    request_load(system_type)                the quote request's fields of a system type (SP-182)
    request_add / request_change             the same edits on its Request Fields table

The owner's decisions (23-11-2026): the quote request's fields stay on each System Type's Request
Fields table; a list field links to the list's values, so list edits show at once; "show only
when <field> = <value>" works with any of the form's list fields, and is checked on the server too
(an SP Field Rule). Removing a field hides it, so the records keep their values. Until the sandbox
(X11, SP-136) exists, every change is live and audited.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from smart_power.sp_core.services.audit import audit
from smart_power.sp_core.services.lists import link_filters, list_names

ADMIN_ROLES = ("SP Admin", "System Manager")
RULE, LIST_VALUE = "SP Field Rule", "SP List Value"
PREFIX = "cx_"
TYPES = {  # the designer's kinds → Frappe field types
	"text": "Data",
	"long_text": "Small Text",
	"number": "Float",
	"money": "Currency",
	"date": "Date",
	"list": "Link",
	"file": "Attach",
	"link": "Link",
	"check": "Check",
}
REQUEST_TYPES = {
	"text": "Data",
	"long_text": "Small Text",
	"number": "Float",
	"list": "List",
	"check": "Check",
}
LAYOUT = ("Section Break", "Column Break", "Tab Break", "Fold")
CONDITION_TYPES = ("Select", "Link")
CACHE_KEY = "sp_field_rules"
HASH_LENGTH = 6  # sp-allow-number: a fieldname for an Arabic-only label, cx_ and six characters


def _admin() -> None:
	frappe.only_for(ADMIN_ROLES)


def _allowed(doctype: str) -> None:
	if doctype not in {f["doctype"] for f in _forms()}:
		frappe.throw(_("{0} is not a form the designer changes.").format(doctype))


def _forms() -> list[dict]:
	from smart_power.sp_core.permissions_matrix import module_map

	out, seen = [], set()
	for module, doctypes in module_map():
		for doctype in doctypes:
			meta = frappe.get_meta(doctype) if frappe.db.exists("DocType", doctype) else None
			if not meta or meta.issingle or meta.istable or doctype in seen:
				continue
			if frappe.local.module_app.get(frappe.scrub(meta.module)) == "frappe":
				continue  # Frappe's own types (User, Workflow, Report) are not forms of the business
			seen.add(doctype)
			out.append({"doctype": doctype, "label": _(doctype), "module": _(module)})
	return out


@frappe.whitelist()
def forms() -> dict:
	_admin()
	types = frappe.get_all(
		LIST_VALUE,
		{"list_name": "System Type", "is_active": 1},
		["name", "value_ar", "code"],
		order_by="sort_order",
	)
	return {
		"forms": _forms(),
		"request_types": [{"name": t.name, "label": t.value_ar or t.code} for t in types],
		"lists": [{"name": n, "label": _(n)} for n in list_names()],
	}


# --- one form -------------------------------------------------------------------------------------


def _customize(doctype: str):
	cf = frappe.get_doc("Customize Form")
	cf.doc_type = doctype
	cf.fetch_to_customize()
	return cf


def _save(cf) -> None:
	cf.hide_success = 1
	cf.save_customization()


def _rules(doctype: str) -> dict:
	return {
		r.fieldname: r
		for r in frappe.get_all(
			RULE, {"document_type": doctype}, ["name", "fieldname", "when_field", "when_value", "reqd"]
		)
	}


@frappe.whitelist()
def load(doctype: str) -> dict:
	_admin()
	_allowed(doctype)
	meta = frappe.get_meta(doctype)
	rules = _rules(doctype)
	fields = []
	for df in meta.fields:
		if df.fieldtype in LAYOUT and df.fieldtype != "Section Break":
			continue
		rule = rules.get(df.fieldname)
		when_df = meta.get_field(rule.when_field) if rule else None
		fields.append(
			{
				"fieldname": df.fieldname,
				"label": _(df.label or df.fieldname),
				"fieldtype": df.fieldtype,
				"section": df.fieldtype == "Section Break",
				"hidden": cint(df.hidden),
				"reqd": cint(df.reqd) or cint(rule.reqd if rule else 0),
				"custom": cint(df.get("is_custom_field")),
				"when": {
					"field": rule.when_field,
					"value": rule.when_value,
					"text": f"{_(when_df.label) if when_df else rule.when_field} = {_(rule.when_value)}",
				}
				if rule
				else None,
			}
		)
	conditions = [
		{"fieldname": df.fieldname, "label": _(df.label or df.fieldname), "options": _choices(df)}
		for df in meta.fields
		if df.fieldtype in CONDITION_TYPES and not df.hidden
	]
	return {"doctype": doctype, "label": _(doctype), "fields": fields, "conditions": conditions}


def _choices(df) -> list[dict]:
	"""A condition field's values, for the value picker: a Select's choices, or the active values
	of the list a list field links to."""
	if df.fieldtype == "Select":
		return [{"value": o, "label": _(o)} for o in (df.options or "").split("\n") if o]
	if df.options == LIST_VALUE and df.get("link_filters"):
		wanted = next((f[3] for f in json.loads(df.link_filters) if f[1] == "list_name"), None)
		if wanted:
			rows = frappe.get_all(LIST_VALUE, {"list_name": wanted, "is_active": 1}, ["name", "value_ar"])
			return [{"value": r.name, "label": r.value_ar or r.name} for r in rows]
	return []


def _fieldname(doctype: str, spec: dict) -> str:
	base = frappe.scrub(spec.get("key") or "") or frappe.scrub(spec.get("label_en") or "")
	if not base or not base.isascii():
		base = frappe.generate_hash(length=HASH_LENGTH)
	name = base if base.startswith(PREFIX) else PREFIX + base
	if frappe.get_meta(doctype).has_field(name):
		frappe.throw(_("The form already has a field {0}.").format(name))
	return name


def _condition(when: dict | None) -> tuple[str | None, str | None]:
	"""depends_on for "show only when field = value"."""
	if not when or not when.get("field"):
		return None, None
	field, value = frappe.scrub(when["field"]), str(when.get("value") or "")
	return field, f"eval:doc.{field}=={json.dumps(value, ensure_ascii=False)}"


def _set_rule(doctype: str, fieldname: str, when: dict | None, reqd: int) -> None:
	name = frappe.db.get_value(RULE, {"document_type": doctype, "fieldname": fieldname})
	if not when or not when.get("field"):
		if name:
			frappe.delete_doc(RULE, name, ignore_permissions=True)
		return
	values = {
		"when_field": frappe.scrub(when["field"]),
		"when_value": str(when.get("value") or ""),
		"reqd": cint(reqd),
	}
	if name:
		doc = frappe.get_doc(RULE, name)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc({"doctype": RULE, "document_type": doctype, "fieldname": fieldname, **values}).insert(
			ignore_permissions=True
		)


@frappe.whitelist(methods=["POST"])
def add_field(doctype: str, spec: dict | str) -> dict:
	"""A new field: {label, label_en?, kind, list?, link?, after?, reqd?, when?: {field, value}}."""
	_admin()
	_allowed(doctype)
	spec = frappe.parse_json(spec) if isinstance(spec, str) else spec
	kind = spec.get("kind")
	if kind not in TYPES:
		frappe.throw(_("Pick the field's type."))
	label = (spec.get("label") or "").strip()
	if not label:
		frappe.throw(_("Enter the field's label."))
	fieldname = _fieldname(doctype, spec)
	row = {"fieldname": fieldname, "label": label, "fieldtype": TYPES[kind]}
	if kind == "list":
		if spec.get("list") not in list_names():
			frappe.throw(_("Pick the list the field takes its values from."))
		row["options"] = LIST_VALUE
		row["link_filters"] = link_filters(spec["list"])  # its active values
	elif kind == "link":
		if not frappe.db.exists("DocType", spec.get("link")):
			frappe.throw(_("Pick the document type the field links to."))
		row["options"] = spec["link"]
	when_field, depends_on = _condition(spec.get("when"))
	reqd = cint(spec.get("reqd"))
	if depends_on:
		row["depends_on"] = depends_on
		if reqd:
			row["mandatory_depends_on"] = depends_on
	else:
		row["reqd"] = reqd
	meta = frappe.get_meta(doctype)
	after = spec.get("after") if meta.has_field(spec.get("after") or "") else meta.fields[-1].fieldname
	# made directly, so it keeps its cx_ name (Customize Form names a new field from its label)
	frappe.get_doc(
		{"doctype": "Custom Field", "dt": doctype, "insert_after": after, "is_system_generated": 0, **row}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=doctype)
	_set_rule(doctype, fieldname, spec.get("when"), reqd)
	audit("Form field added", "DocType", doctype, field=fieldname, label=label, kind=kind, when=when_field)
	return load(doctype)


@frappe.whitelist(methods=["POST"])
def change_field(doctype: str, fieldname: str, spec: dict | str) -> dict:
	"""{hidden?, reqd?, move?: up|down, when?: {field, value} | {}}. Removing a field is hiding it:
	its column and the records' values stay."""
	_admin()
	_allowed(doctype)
	spec = frappe.parse_json(spec) if isinstance(spec, str) else spec
	cf = _customize(doctype)
	row = next((f for f in cf.fields if f.fieldname == fieldname), None)
	if not row:
		frappe.throw(_("The form has no field {0}.").format(fieldname))
	changes = {}
	if "hidden" in spec:
		row.hidden = changes["hidden"] = cint(spec["hidden"])
		if row.hidden:
			row.reqd = 0  # a hidden field cannot be required
	if "when" in spec:
		_field, depends_on = _condition(spec["when"])
		row.depends_on = depends_on
		changes["when"] = spec["when"] or None
	reqd = cint(spec["reqd"]) if "reqd" in spec else cint(row.reqd or row.mandatory_depends_on)
	if "reqd" in spec or "when" in spec:
		row.reqd = 0 if row.depends_on else reqd
		row.mandatory_depends_on = row.depends_on if (row.depends_on and reqd) else None
		changes["reqd"] = reqd
	if spec.get("move") in ("up", "down"):
		i = cf.fields.index(row)
		j = i - 1 if spec["move"] == "up" else i + 1
		if 0 <= j < len(cf.fields):
			cf.fields[i], cf.fields[j] = cf.fields[j], cf.fields[i]
			for idx, f in enumerate(cf.fields, start=1):
				f.idx = idx
		changes["move"] = spec["move"]
	_save(cf)
	if "when" in spec or "reqd" in spec:
		rule = _rules(doctype).get(fieldname)
		when = (
			spec.get("when")
			if "when" in spec
			else ({"field": rule.when_field, "value": rule.when_value} if rule else None)
		)
		_set_rule(doctype, fieldname, when, reqd)
	audit("Form field changed", "DocType", doctype, field=fieldname, **changes)
	return load(doctype)


@frappe.whitelist(methods=["POST"])
def new_list(name: str, label_ar: str | None = None) -> list[dict]:
	"""A new list (X4) the Lists page and list fields offer: a choice added to the list name, with
	its Arabic name as a translation."""
	_admin()
	name = (name or "").strip()
	if not name:
		frappe.throw(_("Enter the list's name."))
	names = list_names()
	if name in names:
		frappe.throw(_("The list {0} already exists.").format(name))
	frappe.make_property_setter(
		{
			"doctype": LIST_VALUE,
			"doctype_or_field": "DocField",
			"fieldname": "list_name",
			"property": "options",
			"value": "\n".join([*names, name]),
			"property_type": "Text",
		}
	)
	if (label_ar or "").strip() and not frappe.db.exists(
		"Translation", {"language": "ar", "source_text": name}
	):
		frappe.get_doc(
			{
				"doctype": "Translation",
				"language": "ar",
				"source_text": name,
				"translated_text": label_ar.strip(),
			}
		).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=LIST_VALUE)
	audit("List created", "DocType", LIST_VALUE, list=name, label_ar=label_ar)
	return forms()["lists"]


# --- the server side of "show only when" ------------------------------------------------------------


def clear_rules() -> None:
	frappe.cache.delete_value(CACHE_KEY)


def _all_rules() -> dict:
	rules = frappe.cache.get_value(CACHE_KEY)
	if rules is None:
		rules = {}
		if frappe.db.table_exists(RULE):
			for r in frappe.get_all(
				RULE, {"reqd": 1}, ["document_type", "fieldname", "when_field", "when_value"]
			):
				rules.setdefault(r.document_type, []).append(r)
		frappe.cache.set_value(CACHE_KEY, rules)
	return rules


def validate_required(doc, method=None) -> None:
	"""doc_events "*" validate: a field required only when shown is checked on the server too."""
	for rule in _all_rules().get(doc.doctype) or []:
		if str(doc.get(rule["when_field"]) or "") == rule["when_value"] and doc.get(rule["fieldname"]) in (
			None,
			"",
		):
			label = doc.meta.get_label(rule["fieldname"])
			frappe.throw(_("{0} is required.").format(_(label)), frappe.MandatoryError)


# --- the quote request's fields, per system type (SP-182's table) -----------------------------------


def _system_type(name: str):
	doc = frappe.get_doc(LIST_VALUE, name)
	if doc.list_name != "System Type":
		frappe.throw(_("{0} is not a system type.").format(name))
	return doc


def _request_rows(doc) -> list[dict]:
	return [
		{
			"fieldname": r.fieldname,
			"label": r.label_ar or r.label,
			"fieldtype": r.fieldtype,
			"reqd": cint(r.reqd),
			"options": r.options,
		}
		for r in doc.request_fields
	]


@frappe.whitelist()
def request_load(system_type: str) -> dict:
	_admin()
	doc = _system_type(system_type)
	return {"system_type": doc.name, "label": doc.value_ar or doc.code, "fields": _request_rows(doc)}


@frappe.whitelist(methods=["POST"])
def request_add(system_type: str, spec: dict | str) -> dict:
	"""A new question on this system type's quote request: {label, label_en?, kind, list?, reqd?, after?}."""
	_admin()
	spec = frappe.parse_json(spec) if isinstance(spec, str) else spec
	if spec.get("kind") not in REQUEST_TYPES:
		frappe.throw(_("The quote request takes text, numbers, lists and yes or no."))
	label = (spec.get("label") or "").strip()
	if not label:
		frappe.throw(_("Enter the field's label."))
	doc = _system_type(system_type)
	fieldname = frappe.scrub(spec.get("label_en") or "") or ""
	if not fieldname or not fieldname.isascii():
		fieldname = PREFIX + frappe.generate_hash(length=HASH_LENGTH)
	row = {
		"label": spec.get("label_en") or label,
		"label_ar": label,
		"fieldtype": REQUEST_TYPES[spec["kind"]],
		"reqd": cint(spec.get("reqd")),
		"fieldname": fieldname,
	}
	if spec["kind"] == "list":
		row["options"] = spec.get("list")
	rows = [r.as_dict() for r in doc.request_fields]
	names = [r["fieldname"] for r in rows]
	at = names.index(spec["after"]) + 1 if spec.get("after") in names else len(rows)
	rows.insert(at, row)
	doc.set(
		"request_fields",
		[
			{k: r.get(k) for k in ("fieldname", "label", "label_ar", "fieldtype", "reqd", "options")}
			for r in rows
		],
	)
	doc.save(ignore_permissions=True)
	audit("Request field added", LIST_VALUE, doc.name, field=fieldname, label=label)
	return request_load(system_type)


@frappe.whitelist(methods=["POST"])
def request_change(system_type: str, fieldname: str, spec: dict | str) -> dict:
	"""{reqd?, move?: up|down, remove?}. A removed question leaves the old requests' answers."""
	_admin()
	spec = frappe.parse_json(spec) if isinstance(spec, str) else spec
	doc = _system_type(system_type)
	rows = list(doc.request_fields)
	row = next((r for r in rows if r.fieldname == fieldname), None)
	if not row:
		frappe.throw(_("The request has no field {0}.").format(fieldname))
	if "reqd" in spec:
		row.reqd = cint(spec["reqd"])
	if spec.get("move") in ("up", "down"):
		i = rows.index(row)
		j = i - 1 if spec["move"] == "up" else i + 1
		if 0 <= j < len(rows):
			rows[i], rows[j] = rows[j], rows[i]
	if cint(spec.get("remove")):
		rows.remove(row)
	doc.set(
		"request_fields",
		[
			{k: r.get(k) for k in ("fieldname", "label", "label_ar", "fieldtype", "reqd", "options")}
			for r in rows
		],
	)
	doc.save(ignore_permissions=True)
	audit("Request field changed", LIST_VALUE, doc.name, field=fieldname, **spec)
	return request_load(system_type)
