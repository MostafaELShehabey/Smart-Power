"""Quote requests (SP-47, C3): each system type asks only its own fields.

The fields live in the System Type's Extra Data (SP List Value meta_json, X4) under
"request_fields", so the admin changes them without a developer (SP-132 gives them a screen):

    {"request_fields": [{"fieldname": "well_depth_m", "label": "Well Depth (m)",
                          "label_ar": "عمق البئر (متر)", "fieldtype": "Float", "reqd": 0}]}

The answers are stored on the case as Request Details (JSON).
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

from smart_power.sp_core.setup.seed import defaults

LIST_VALUE = "SP List Value"
SYSTEM_TYPE_LIST = "System Type"
META_KEY = "request_fields"
NUMBER_TYPES = {"Float": flt, "Int": cint}
TEXT_TYPES = {"Data", "Small Text", "Select"}
FIELD_TYPES = set(NUMBER_TYPES) | TEXT_TYPES | {"Check"}


def request_fields(system_type: str | None) -> list[dict]:
	"""The request fields of a system type (an SP List Value name), in order."""
	if not system_type:
		return []
	meta = _meta(system_type)
	return [f for f in meta.get(META_KEY) or [] if f.get("fieldname") and f.get("fieldtype") in FIELD_TYPES]


def clean_details(system_type: str | None, details) -> dict:
	"""Keep only the system type's fields, as numbers where they are numbers; check required ones."""
	if isinstance(details, str):
		details = json.loads(details or "{}")
	details = details or {}
	cleaned = {}
	for field in request_fields(system_type):
		name, kind = field["fieldname"], field["fieldtype"]
		value = details.get(name)
		if value in (None, ""):
			if cint(field.get("reqd")):
				frappe.throw(
					_("{0} is required for this system type.").format(_label(field)), frappe.MandatoryError
				)
			continue
		if kind in NUMBER_TYPES:
			value = NUMBER_TYPES[kind](value)
			if value < 0:
				frappe.throw(_("{0} cannot be negative.").format(_label(field)))
		elif kind == "Check":
			value = cint(value)
		elif (
			kind == "Select"
			and field.get("options")
			and cstr(value) not in cstr(field["options"]).split("\n")
		):
			frappe.throw(_("{0}: {1} is not one of the choices.").format(_label(field), value))
		else:
			value = cstr(value).strip()
		cleaned[name] = value
	return cleaned


def seed_request_fields() -> None:
	"""Give each seeded system type its request fields, unless the admin has set them already."""
	seeds = {k: v for k, v in defaults().get(META_KEY, {}).items() if not k.startswith("_")}
	for code, fields in seeds.items():
		name = frappe.db.get_value(LIST_VALUE, {"list_name": SYSTEM_TYPE_LIST, "code": code})
		if not name:
			continue
		meta = _meta(name)
		if META_KEY in meta:
			continue
		meta[META_KEY] = fields
		frappe.db.set_value(LIST_VALUE, name, "meta_json", json.dumps(meta, ensure_ascii=False))


def _meta(system_type: str) -> dict:
	raw = frappe.db.get_value(LIST_VALUE, system_type, "meta_json")
	if isinstance(raw, dict):
		return raw
	return json.loads(raw) if raw else {}


def _label(field: dict) -> str:
	if frappe.local.lang == "ar" and field.get("label_ar"):
		return field["label_ar"]
	return _(field.get("label") or field["fieldname"])
