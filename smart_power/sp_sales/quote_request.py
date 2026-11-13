"""Quote requests (SP-47, C3): each system type asks only its own fields.

The fields live in the System Type's Extra Data (SP List Value meta_json, X4) under
"request_fields", so the admin changes them without a developer (SP-132 gives them a screen):

    {"request_fields": [{"fieldname": "well_depth_m", "label": "Well Depth (m)",
                          "label_ar": "عمق البئر (متر)", "fieldtype": "Float", "reqd": 0}]}

The answers are stored on the case as Request Details (JSON).

The C3 form calls three methods: `check_mobile` while the mobile is typed (a returning
customer's file opens instead of a duplicate), `followup_owners` for the owner picker, and
`create_quote_request`, which finds or creates the customer and opens the case, both or
neither.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

from smart_power.sp_core.setup.seed import defaults
from smart_power.sp_sales.customer import find_by_mobile, is_valid_mobile, normalize_mobile

CASE = "SP Case"
LIST_VALUE = "SP List Value"
FOLLOWUP_ROLE = "SP Customer Followup"
CLOSED_STATUSES = ("Won", "Lost")
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


@frappe.whitelist()
def get_request_fields(system_type: str) -> list[dict]:
	"""The fields the form shows for a system type."""
	frappe.has_permission(CASE, "create", throw=True)
	return request_fields(system_type)


@frappe.whitelist()
def check_mobile(mobile: str) -> dict:
	"""Is this a valid mobile, and does the customer already exist (with how many open cases)?"""
	frappe.has_permission(CASE, "create", throw=True)
	number = normalize_mobile(mobile)
	result = {"mobile": number, "valid": is_valid_mobile(number), "customer": None}
	customer = find_by_mobile(number) if result["valid"] else None
	if customer:
		info = frappe.db.get_value(
			"Customer", customer, ["customer_name", "sp_tier", "sp_region"], as_dict=True
		)
		result.update(
			customer=customer,
			customer_name=info.customer_name,
			tier=info.sp_tier,
			region=info.sp_region,
			open_cases=frappe.db.count(CASE, {"customer": customer, "status": ("not in", CLOSED_STATUSES)}),
		)
	return result


@frappe.whitelist()
def followup_owners() -> list[dict]:
	"""Enabled users who follow up customers: the choices for the case's follow-up owner."""
	frappe.has_permission(CASE, "create", throw=True)
	users = frappe.get_all("Has Role", {"role": FOLLOWUP_ROLE, "parenttype": "User"}, pluck="parent")
	return frappe.get_all(
		"User",
		filters={"name": ("in", users or [""]), "enabled": 1},
		fields=["name", "full_name"],
		order_by="full_name asc",
	)


@frappe.whitelist(methods=["POST"])
def create_quote_request(request: dict | str) -> dict:
	"""Find or create the customer by mobile, then open a case in "Quote request".

	request: system_type, mobile, customer_name, tier, region (new customers), channel,
	follow_up_owner, site_visit_needed, request_notes, details ({fieldname: value}).
	"""
	frappe.has_permission(CASE, "create", throw=True)
	request = frappe.parse_json(request) if isinstance(request, str) else frappe._dict(request)
	if not request.get("system_type"):
		frappe.throw(_("Choose the system type first."), frappe.MandatoryError)
	mobile = normalize_mobile(request.get("mobile"))
	if not is_valid_mobile(mobile):
		frappe.throw(
			_("{0} is not a valid Egyptian mobile.").format(frappe.bold(request.get("mobile") or ""))
		)

	# the customer and the case are saved together or not at all
	frappe.db.savepoint("sp_quote_request")
	try:
		customer, new_customer = find_by_mobile(mobile), False
		if not customer:
			if not cstr(request.get("customer_name")).strip():
				frappe.throw(_("Enter the customer's name: this mobile is new."), frappe.MandatoryError)
			customer = (
				frappe.get_doc(
					{
						"doctype": "Customer",
						"customer_name": cstr(request.customer_name).strip(),
						"sp_mobile": mobile,
						"sp_tier": request.get("tier") or None,
						"sp_region": request.get("region") or None,
					}
				)
				.insert()
				.name
			)
			new_customer = True

		case = frappe.get_doc(
			{
				"doctype": CASE,
				"customer": customer,
				"channel": request.get("channel"),
				"requested_by": frappe.session.user,
				"follow_up_owner": request.get("follow_up_owner") or _default_followup_owner(),
				"system_types": [{"system_type": request.system_type}],
				"request_details": clean_details(request.system_type, request.get("details")),
				"site_visit_needed": cint(request.get("site_visit_needed")),
				"request_notes": request.get("request_notes"),
			}
		).insert()
	except Exception:
		frappe.db.rollback(save_point="sp_quote_request")
		raise
	return {"case": case.name, "customer": customer, "new_customer": new_customer}


def _default_followup_owner() -> str | None:
	"""The person taking the request, when they follow up customers themselves."""
	return frappe.session.user if FOLLOWUP_ROLE in frappe.get_roles() else None


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
