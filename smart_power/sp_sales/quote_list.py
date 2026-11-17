"""Q1 quotes list (SP-64): what the list shows of each quote, kept in step with its case.

- sp_follow_up_owner, sp_system_type and sp_size (kW or HP) come from the case, so the list can
  show and filter them; a change on the case reaches its quotes.
- sp_is_latest marks the newest live version of each quote (its chain of versions, sp_root): the
  list shows only those by default, and a toggle shows every version.
- The margin column is the cost permlevel's: the list and its export leave it out for whoever
  may not read it (the follow-up roles).
"""

import json

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.utils import flt, today

QUOTATION, CASE = "Quotation", "SP Case"
CANCELLED = DocStatus.cancelled()
SIZE_KEYS = (("kw", "kW"), ("hp", "HP"))
CASE_FIELDS = ("follow_up_owner", "system_types", "request_details")


def _case_values(case: str | None) -> dict:
	"""{sp_follow_up_owner, sp_system_type, sp_size} for a case."""
	if not case or not frappe.db.exists(CASE, case):
		return {"sp_follow_up_owner": None, "sp_system_type": None, "sp_size": None}
	row = frappe.db.get_value(CASE, case, ["follow_up_owner", "request_details"], as_dict=True)
	system_type = frappe.db.get_value(
		"SP Case System Type", {"parent": case, "parenttype": CASE}, "system_type", order_by="idx asc"
	)
	return {
		"sp_follow_up_owner": row.follow_up_owner,
		"sp_system_type": system_type,
		"sp_size": size_of(row.request_details),
	}


def size_of(details, design_inputs=None) -> str | None:
	""" "15 kW" or "20 HP" from the request (or the quote's design inputs)."""
	for source in (details, design_inputs):
		if isinstance(source, str):
			try:
				source = json.loads(source or "{}")
			except ValueError:
				source = {}
		for key, unit in SIZE_KEYS:
			value = flt((source or {}).get(key))
			if value:
				return f"{value:g} {unit}"
	return None


def set_list_fields(doc, method=None) -> None:
	"""Quotation validate: the case's follow-up owner, system and size, and whether this is the
	newest version of its chain (set here too, so a later save never writes a stale flag)."""
	values = _case_values(doc.get("sp_case"))
	if not values["sp_size"]:
		values["sp_size"] = size_of(None, doc.get("sp_design_inputs"))
	doc.update(values)
	doc.sp_is_latest = 0 if _newer_version(doc) else 1


def _newer_version(doc) -> bool:
	if not doc.get("sp_root"):
		return False  # the first version of a new chain
	return bool(
		frappe.db.exists(
			QUOTATION,
			{
				"sp_root": doc.sp_root,
				"docstatus": ("<", CANCELLED),
				"sp_version": (">", doc.get("sp_version") or 0),
				"name": ("!=", doc.name or ""),
			},
		)
	)


def refresh_latest(root: str | None, leaving: str | None = None) -> None:
	"""Mark the newest live version of a chain as the latest, the others not (`leaving`: a
	version being deleted)."""
	if not root:
		return
	versions = frappe.get_all(
		QUOTATION,
		{"sp_root": root, "docstatus": ("<", CANCELLED), "name": ("!=", leaving or "")},
		["name", "sp_is_latest"],
		order_by="sp_version desc, creation desc",
	)
	for i, v in enumerate(versions):
		latest = 1 if i == 0 else 0
		if v.sp_is_latest != latest:
			frappe.db.set_value(QUOTATION, v.name, "sp_is_latest", latest, update_modified=False)
	# a cancelled version is never the latest
	for name in frappe.get_all(
		QUOTATION, {"sp_root": root, "docstatus": CANCELLED, "sp_is_latest": 1}, pluck="name"
	):
		frappe.db.set_value(QUOTATION, name, "sp_is_latest", 0, update_modified=False)


def on_quote_change(doc, method=None) -> None:
	"""Quotation after_insert / on_cancel / on_trash: the chain's latest moves."""
	root = doc.get("sp_root") or (doc.name if method == "after_insert" else None)
	leaving = doc.name if method == "on_trash" else None
	refresh_latest(root, leaving)


def on_case_change(doc, method=None) -> None:
	"""SP Case on_update: its quotes follow the follow-up owner, system and size."""
	before = doc.get_doc_before_save()
	if before and all(_same(before.get(f), doc.get(f)) for f in CASE_FIELDS):
		return
	values = _case_values(doc.name)
	for q in frappe.get_all(QUOTATION, {"sp_case": doc.name}, ["name", "sp_design_inputs"]):
		row = dict(values)
		if not row["sp_size"]:
			row["sp_size"] = size_of(None, q.sp_design_inputs)
		frappe.db.set_value(QUOTATION, q.name, row, update_modified=False)


def _same(a, b) -> bool:
	if isinstance(a, list) or isinstance(b, list):
		return [r.get("system_type") for r in a or []] == [r.get("system_type") for r in b or []]
	return (a or None) == (b or None)


def backfill() -> None:
	"""Fill the list fields and the latest flags on the quotes that exist (patch)."""
	for q in frappe.get_all(QUOTATION, {"sp_case": ("is", "set")}, ["name", "sp_case", "sp_design_inputs"]):
		row = _case_values(q.sp_case)
		if not row["sp_size"]:
			row["sp_size"] = size_of(None, q.sp_design_inputs)
		frappe.db.set_value(QUOTATION, q.name, row, update_modified=False)
	for root in frappe.get_all(QUOTATION, {"sp_root": ("is", "set")}, pluck="sp_root", distinct=True):
		refresh_latest(root)


# --- export ---------------------------------------------------------------------------------------

# Q1's actions include export: the quote creators and the follow-up roles export the list (the
# follow-up export leaves the cost permlevel out, as the list does).
EXPORT_ROLES = (
	"SP Quote Creator",
	"SP System Designer",
	"SP Customer Followup",
	"SP Followup All",
	"SP Admin",
)


def sync_export_permissions() -> None:
	"""Give the Q1 roles Export on Quotation (permlevel 0); rows the admin changed are kept."""
	from frappe.permissions import add_permission, update_permission_property

	for role in EXPORT_ROLES:
		if not frappe.db.exists("Role", role):
			continue
		key = {"parent": QUOTATION, "role": role, "permlevel": 0, "if_owner": 0}
		if frappe.db.exists("Custom DocPerm", key):
			continue
		add_permission(QUOTATION, role, 0)
		for ptype in ("export", "report"):
			update_permission_property(QUOTATION, role, 0, ptype, 1, validate=False)
	frappe.clear_cache(doctype=QUOTATION)


# --- duplicate for another customer -------------------------------------------------------------

QUOTE_CREATOR_ROLES = ("SP Quote Creator", "SP System Designer")
CASE_COPY_FIELDS = ("channel", "source", "campaign", "payment_method", "request_details", "request_notes")


@frappe.whitelist(methods=["POST"])
def duplicate_for_customer(name: str, customer: str) -> dict:
	"""Copy a quote into a new case for another customer, as its first draft version (Q1).

	The case takes the source case's system types, request answers and loads (a starting point to
	edit); its follow-up owner is the customer's own (so no colleague's customer is taken), else
	the source case's. Whoever duplicates must be able to read the customer. The quote keeps the
	lines and design inputs, never the source's versions, approval or discounts. Returns
	{"case", "quotation"}."""
	from smart_power.sp_sales.quote_request import customer_owner

	source = frappe.get_doc(QUOTATION, name)
	source.check_permission("read")
	if not source.get("sp_case"):
		frappe.throw(_("Only a quote of a case can be duplicated for another customer."))
	# the quote creators duplicate their own work; the case is opened for them (they do not
	# create cases themselves)
	frappe.has_permission(QUOTATION, "create", throw=True)
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found.").format(customer), frappe.DoesNotExistError)
	frappe.get_doc("Customer", customer).check_permission("read")
	old_case = frappe.get_doc(CASE, source.sp_case)
	creator = (
		frappe.session.user
		if set(QUOTE_CREATOR_ROLES) & set(frappe.get_roles())
		else old_case.quote_creator or source.get("sp_quote_creator")
	)
	case = frappe.get_doc(
		{
			"doctype": CASE,
			"customer": customer,
			"requested_by": frappe.session.user,
			"follow_up_owner": customer_owner(customer) or old_case.follow_up_owner,
			"quote_creator": creator,
			"system_types": [{"system_type": r.system_type} for r in old_case.system_types],
			"loads": [
				{
					k: v
					for k, v in r.as_dict().items()
					if k not in ("name", "parent", "parentfield", "parenttype", "idx")
				}
				for r in old_case.loads
			],
			**{f: old_case.get(f) for f in CASE_COPY_FIELDS},
		}
	).insert(ignore_permissions=True)

	doc = frappe.copy_doc(source, ignore_no_copy=False)
	doc.docstatus = 0
	for row in doc.get_all_children():
		row.docstatus = 0
	doc.update(
		{
			"party_name": customer,
			"customer_name": frappe.db.get_value("Customer", customer, "customer_name"),
			"sp_case": case.name,
			"sp_quote_creator": creator,
			"sp_root": None,
			"sp_previous_version": None,
			"sp_version": None,
			"sp_option_label": None,
			"sp_is_approved": 0,
			"sp_superseded": 0,
			"sp_needs_repricing": 0,
			"transaction_date": today(),
			"valid_till": None,
		}
	)
	doc.set("sp_discounts", [])
	for field in (
		"customer_address",
		"address_display",
		"contact_person",
		"contact_display",
		"contact_mobile",
		"contact_email",
		"shipping_address_name",
		"shipping_address",
	):
		if doc.meta.has_field(field):
			doc.set(field, None)
	doc.insert()
	return {"case": case.name, "quotation": doc.name}
