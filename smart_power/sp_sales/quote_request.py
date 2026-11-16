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
import mimetypes

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

from smart_power.sp_core.setup.seed import defaults
from smart_power.sp_sales.customer import find_by_mobile, is_valid_mobile, normalize_mobile

CASE = "SP Case"
LIST_VALUE = "SP List Value"
FOLLOWUP_ROLE = "SP Customer Followup"
CLOSED_STATUSES = ("Won", "Lost")
ADMIN_ROLE = "SP Admin"
QUOTE_CREATOR_ROLE = "SP Quote Creator"
FOLLOWUP_ALL_ROLE = "SP Followup All"
INSTALLATION_MANAGER_ROLE = "SP Installation Manager"
MARKETING_ROLE = "SP Marketing Agent"
MARKETING_CHANNEL = "Marketing"
SOURCE_LIST = "Lead Source"
INVALID, NEW, MINE, FEATURED, COLLEAGUE = "invalid", "new", "mine", "featured", "colleague"
SYSTEM_TYPE_LIST = "System Type"
META_KEY = "request_fields"
NUMBER_TYPES = {"Float": flt, "Int": cint}
TEXT_TYPES = {"Data", "Small Text", "Select"}
LOAD_TABLE = "Load Table"  # shows the case's load table (SP Load Line) instead of a single value
FIELD_TYPES = set(NUMBER_TYPES) | TEXT_TYPES | {"Check", LOAD_TABLE}
PAYMENT_LIST = "Financing Type"
QUOTE_REQUEST_TASK, SITE_SURVEY_TASK = "Quote Request", "Site Survey"
TASK_OPEN, TASK_CANCELLED = "Open", "Cancelled"


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
		if kind == LOAD_TABLE:
			continue  # the loads are rows on the case, checked by check_loads
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


def summarize_request(system_type: str | None, details, load_count: int = 0) -> dict:
	"""For the Q3 queue (SP-48): the request's answers as "label: value" lines (key data), and
	the labels of the type's fields left empty (missing fields). Read at display time, so a
	field the admin adds later shows as missing on older requests."""
	if isinstance(details, str):
		details = json.loads(details or "{}")
	details = details or {}
	key_data, missing = [], []
	for field in request_fields(system_type):
		label = _label(field)
		if field["fieldtype"] == LOAD_TABLE:
			if load_count:
				key_data.append(f"{label}: {load_count}")
			else:
				missing.append(label)
			continue
		value = details.get(field["fieldname"])
		if value in (None, ""):
			missing.append(label)
		elif field["fieldtype"] == "Check":
			key_data.append(f"{label}: {_('Yes') if cint(value) else _('No')}")
		else:
			key_data.append(f"{label}: {value}")
	return {"key_data": key_data, "missing_fields": missing}


@frappe.whitelist()
def get_request_fields(system_type: str) -> list[dict]:
	"""The fields the form shows for a system type."""
	frappe.has_permission(CASE, "create", throw=True)
	return request_fields(system_type)


@frappe.whitelist()
def check_mobile(mobile: str) -> dict:
	"""Look a mobile up for the request form (SP-47).

	status: invalid, new, mine, featured or colleague. A colleague's customer (owned by
	someone else and not featured) returns only the owner's name, never the customer's
	details; the form offers "ask the admin to reassign" instead of saving.
	"""
	frappe.has_permission(CASE, "create", throw=True)
	number = normalize_mobile(mobile)
	if not is_valid_mobile(number):
		return {"mobile": number, "valid": False, "status": INVALID, "customer": None}
	customer = find_by_mobile(number)
	if not customer:
		return {"mobile": number, "valid": True, "status": NEW, "customer": None}
	status, owner = customer_status(customer)
	if status == COLLEAGUE:
		return {
			"mobile": number,
			"valid": True,
			"status": COLLEAGUE,
			"customer": None,
			"owner_name": frappe.utils.get_fullname(owner),
		}
	info = frappe.db.get_value("Customer", customer, ["customer_name", "sp_tier", "sp_region"], as_dict=True)
	return {
		"mobile": number,
		"valid": True,
		"status": status,
		"customer": customer,
		"customer_name": info.customer_name,
		"tier": info.sp_tier,
		"region": info.sp_region,
		"open_cases": frappe.db.count(CASE, {"customer": customer, "status": ("not in", CLOSED_STATUSES)}),
	}


def customer_owner(customer: str) -> str | None:
	"""Who follows the customer up: its Follow-up Owner, else the owner of its latest case."""
	owner = frappe.db.get_value("Customer", customer, "sp_owner_user")
	if owner:
		return owner
	latest = frappe.get_all(
		CASE, {"customer": customer}, ["follow_up_owner"], order_by="creation desc", limit=1
	)
	return latest[0].follow_up_owner if latest else None


def customer_status(customer: str, user: str | None = None) -> tuple[str, str | None]:
	"""(mine | featured | colleague, owner) for the user taking the request."""
	user = user or frappe.session.user
	owner = customer_owner(customer)
	if frappe.db.get_value("Customer", customer, "sp_featured"):
		return FEATURED, owner
	if not owner or owner == user or _sees_all_customers(user):
		return MINE, owner
	return COLLEAGUE, owner


@frappe.whitelist(methods=["POST"])
def request_reassign(mobile: str) -> int:
	"""Ask the admins to move a colleague's customer to me (SP-47): one task per admin."""
	frappe.has_permission(CASE, "create", throw=True)
	customer = find_by_mobile(normalize_mobile(mobile))
	if not customer:
		frappe.throw(_("No customer has this mobile."))
	owner = customer_owner(customer)
	requester = frappe.utils.get_fullname(frappe.session.user)
	admins = _users_with(ADMIN_ROLE)
	for admin in admins:
		frappe.get_doc(
			{
				"doctype": "SP Task",
				"subject": _("{0} asks to take over customer {1} from {2}").format(
					requester, customer, frappe.utils.get_fullname(owner)
				),
				"task_type": "Reassign Request",
				"assigned_to": admin,
				"reference_doctype": "Customer",
				"reference_name": customer,
			}
		).insert(ignore_permissions=True)
	return len(admins)


def _sees_all_customers(user: str) -> bool:
	"""The admin can reassign directly, so a colleague's customer is not hidden from them."""
	return user == "Administrator" or bool({ADMIN_ROLE, "System Manager"} & set(frappe.get_roles(user)))


def _users_with(role: str) -> list[str]:
	users = frappe.get_all("Has Role", {"role": role, "parenttype": "User"}, pluck="parent")
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")


@frappe.whitelist()
def followup_owners() -> list[dict]:
	"""Enabled users who follow up customers: the choices for the case's follow-up owner.
	`lead` marks the follow-up lead (SP Followup All, كاميليا), marketing's default."""
	frappe.has_permission(CASE, "create", throw=True)
	users = frappe.get_all("Has Role", {"role": FOLLOWUP_ROLE, "parenttype": "User"}, pluck="parent")
	leads = set(_users_with(FOLLOWUP_ALL_ROLE))
	owners = frappe.get_all(
		"User",
		filters={"name": ("in", users or [""]), "enabled": 1},
		fields=["name", "full_name"],
		order_by="full_name asc",
	)
	for owner in owners:
		owner["lead"] = int(owner.name in leads)
	return owners


@frappe.whitelist(methods=["POST"])
def create_quote_request(request: dict | str) -> dict:
	"""Find or create the customer by mobile, then open a case in "Quote request".

	request: system_type, mobile, customer_name, tier, region (new customers), channel,
	follow_up_owner, location_text, geo, payment_method, site_visit_needed, request_notes,
	details ({fieldname: value}), loads ([{device, qty, watts, day_hours, night_hours}]),
	photos (optional: names of image Files the user has just uploaded, attached to the case) and
	indicative_inputs (optional, SP-49: the specs priced on the indicative page, recorded with
	their price on the case).
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

	if request.get("channel") == MARKETING_CHANNEL and not request.get("source"):
		frappe.throw(_("A marketing request needs its source."), frappe.MandatoryError)
	details = clean_details(request.system_type, request.get("details"))
	check_loads(request.system_type, request.get("loads"))

	# the customer and the case are saved together or not at all
	frappe.db.savepoint("sp_quote_request")
	try:
		customer, new_customer = find_by_mobile(mobile), False
		if customer and customer_status(customer)[0] == COLLEAGUE:
			frappe.throw(
				_("This customer is followed up by {0}. Ask the admin to reassign them.").format(
					frappe.bold(frappe.utils.get_fullname(customer_owner(customer)))
				),
				frappe.PermissionError,
			)
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
				"source": request.get("source") or None,
				"system_types": [{"system_type": request.system_type}],
				"request_details": details,
				"site_visit_needed": cint(request.get("site_visit_needed")),
				"request_notes": request.get("request_notes"),
				"location_text": request.get("location_text"),
				"geo": request.get("geo"),
				"payment_method": request.get("payment_method") or None,
				"loads": request.get("loads") or [],
			}
		)
		if request.get("indicative_inputs"):
			# priced first on the indicative page (SP-49): the value, date and specs go on the case
			from smart_power.sp_quotes.indicative import record

			record(case, request.system_type, frappe.parse_json(request.indicative_inputs))
		case.insert()
		attach_photos(case, request.get("photos"))
	except Exception:
		frappe.db.rollback(save_point="sp_quote_request")
		raise
	after_request(case)
	return {"case": case.name, "customer": customer, "new_customer": new_customer}


def attach_photos(case, photos) -> None:
	"""Attach the request's photos to the case. Only the user's own unattached images qualify."""
	for name in photos or []:
		file = frappe.get_doc("File", name)
		if file.owner != frappe.session.user or file.attached_to_doctype or file.is_folder:
			frappe.throw(_("Photo {0} cannot be added to this request.").format(frappe.bold(file.file_name)))
		if not (mimetypes.guess_type(file.file_url or file.file_name or "")[0] or "").startswith("image/"):
			frappe.throw(_("{0} is not a photo.").format(frappe.bold(file.file_name)))
		file.attached_to_doctype, file.attached_to_name = CASE, case.name
		file.save(ignore_permissions=True)


def after_request(case) -> None:
	"""A saved request: tell the admins and quote creators, give each quote creator a
	"Quote Request" task (the first to take it closes the others, SP-48), and ask the
	installation managers for a site survey when one is needed (SP-95 adds the survey)."""
	from smart_power.notify import send

	subject = _("New quote request: {0} ({1})").format(case.customer_name or case.customer, case.name)
	send(
		"new_request",
		sorted(set(_users_with(ADMIN_ROLE)) | set(_users_with(QUOTE_CREATOR_ROLE))),
		CASE,
		case.name,
		subject,
		from_user=frappe.session.user,
	)
	for user in _users_with(QUOTE_CREATOR_ROLE):
		_task(
			case,
			QUOTE_REQUEST_TASK,
			user,
			_("Quote request: {0}").format(case.customer_name or case.customer),
		)
	if case.site_visit_needed:
		for user in _users_with(INSTALLATION_MANAGER_ROLE):
			_task(
				case,
				SITE_SURVEY_TASK,
				user,
				_("Site survey for {0}").format(case.customer_name or case.customer),
			)


def hand_over_request(case) -> None:
	"""The request has a quote creator: the other "Quote Request" tasks close, and the quote
	creator keeps (or gets) their own."""
	open_tasks = frappe.get_all(
		"SP Task",
		filters={
			"reference_doctype": CASE,
			"reference_name": case.name,
			"task_type": QUOTE_REQUEST_TASK,
			"status": TASK_OPEN,
		},
		fields=["name", "assigned_to"],
	)
	for task in open_tasks:
		if task.assigned_to != case.quote_creator:
			frappe.db.set_value("SP Task", task.name, "status", TASK_CANCELLED)
	if not any(t.assigned_to == case.quote_creator for t in open_tasks):
		_task(
			case,
			QUOTE_REQUEST_TASK,
			case.quote_creator,
			_("Quote request: {0}").format(case.customer_name or case.customer),
		)


def _task(case, task_type: str, user: str, subject: str) -> None:
	frappe.get_doc(
		{
			"doctype": "SP Task",
			"subject": subject,
			"task_type": task_type,
			"assigned_to": user,
			"due_at": case.get("quote_due_at"),
			"reference_doctype": CASE,
			"reference_name": case.name,
		}
	).insert(ignore_permissions=True)


def _default_followup_owner() -> str | None:
	"""The person taking the request when they follow up customers; marketing hands its
	requests to كاميليا (the follow-up lead, SP Followup All) unless another owner is picked."""
	roles = frappe.get_roles()
	if FOLLOWUP_ROLE in roles:
		return frappe.session.user
	if MARKETING_ROLE in roles:
		leads = _users_with(FOLLOWUP_ALL_ROLE)
		return leads[0] if leads else None
	return None


def needs_loads(system_type: str | None) -> dict | None:
	"""The system type's load-table field, if it asks for one."""
	return next((f for f in request_fields(system_type) if f["fieldtype"] == LOAD_TABLE), None)


def check_loads(system_type: str | None, loads) -> None:
	"""A type whose load table is required needs at least one load line."""
	field = needs_loads(system_type)
	if field and cint(field.get("reqd")) and not loads:
		frappe.throw(_("{0} is required for this system type.").format(_label(field)), frappe.MandatoryError)


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
