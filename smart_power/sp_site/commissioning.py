"""PR1 programming and commissioning (SP-97): one per station system.

- The inverter (brand, model, serial), its settings file (the latest of that brand and model in
  the settings library is suggested, SP-98) and the remote-support ID.
- Test readings and the checklist come from the system type's template (its Extra Data under
  "commissioning", or the "*" template), editable on the record; every checklist item must be
  done before submitting, and the refusal names the ones that are not.
- Component serials with their warranty: months from the item (warranty years x 12, else
  ERPNext's warranty days) when not typed; the warranty ends the day before the same date
  that many months after the operation date.
- On submit the station's operation date is the latest of its systems'; once every system of the
  station is commissioned, the project managers (أميرة) get a "Technical Close" task.
- Cancelling (not once the station is technically closed, except by the admin) puts the
  station's operation date back and withdraws the close task.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, getdate

from smart_power.sp_core.inbox import close_tasks, create_task
from smart_power.sp_core.setup.seed import defaults

COMMISSIONING, STATION, LIST_VALUE = "SP Commissioning", "SP Station", "SP List Value"
SETTINGS_FILE = "SP Settings File"
META_KEY, ANY_TYPE = "commissioning", "*"
SYSTEM_TYPE_LIST, BRAND_LIST = "System Type", "Inverter Brand"
CANCELLED_STATION = "Cancelled"
CANCELLED_DOC = 2  # sp-allow-number: Frappe docstatus
CLOSED_STATIONS = ("Technically closed", "Financially closed")
PROJECT_MANAGER_ROLE = "SP Project Manager"
ADMIN_ROLES = ("SP Admin", "System Manager")
TECH_CLOSE_TASK = "Technical Close"
MONTHS_PER_YEAR = 12  # sp-allow-number: a calendar fact, not a business value
DAYS_PER_MONTH = 30  # sp-allow-number: ERPNext keeps an item's warranty in days


# --- the template -------------------------------------------------------------------------------


def template(system_type: str | None) -> dict:
	"""The system type's checklist and readings, else the "*" template's."""
	meta = _meta(system_type) if system_type else {}
	if meta.get(META_KEY):
		return meta[META_KEY]
	return defaults().get(META_KEY, {}).get(ANY_TYPE, {})


def _meta(name: str) -> dict:
	raw = frappe.db.get_value(LIST_VALUE, name, "meta_json")
	if isinstance(raw, dict):
		return raw
	return json.loads(raw) if raw else {}


def _text(row: dict, key: str) -> str:
	if (frappe.local.lang or "").startswith("ar") and row.get(f"{key}_ar"):
		return row[f"{key}_ar"]
	return row.get(key) or ""


def seed_commissioning_templates() -> None:
	"""Give each system type its commissioning template, unless the admin has set one."""
	seeds = defaults().get(META_KEY, {})
	for row in frappe.get_all(LIST_VALUE, {"list_name": SYSTEM_TYPE_LIST}, ["name", "code"]):
		seed = seeds.get(row.code) or seeds.get(ANY_TYPE)
		meta = _meta(row.name)
		if not seed or META_KEY in meta:
			continue
		meta[META_KEY] = seed
		frappe.db.set_value(LIST_VALUE, row.name, "meta_json", json.dumps(meta, ensure_ascii=False))


# --- the form -----------------------------------------------------------------------------------


@frappe.whitelist()
def station_systems(station: str) -> list[dict]:
	"""The station's systems to choose from, with the ones already commissioned marked."""
	frappe.get_doc(STATION, station).check_permission("read")
	done = set(
		frappe.get_all(
			COMMISSIONING, {"station": station, "docstatus": ("!=", CANCELLED_DOC)}, pluck="system_row"
		)
	)
	rows = frappe.get_all(
		"SP Station System",
		{"parent": station, "parenttype": STATION},
		["name", "idx", "system_type", "capacity_kw", "hp"],
		order_by="idx asc",
	)
	types = {
		r.name: r.value_ar if (frappe.local.lang or "").startswith("ar") else r.value_en
		for r in frappe.get_all(LIST_VALUE, {"list_name": SYSTEM_TYPE_LIST}, ["name", "value_ar", "value_en"])
	}
	out = []
	for r in rows:
		size = (
			f"{flt(r.capacity_kw):g} kW" if flt(r.capacity_kw) else (f"{flt(r.hp):g} HP" if flt(r.hp) else "")
		)
		parts = [f"{r.idx}", types.get(r.system_type) or r.system_type, size]
		label = " · ".join(p for p in parts if p)
		out.append({"value": r.name, "label": label, "system_type": r.system_type, "done": r.name in done})
	return out


@frappe.whitelist()
def defaults_for(system_type: str | None = None) -> dict:
	"""The checklist and readings rows a new commissioning starts with."""
	frappe.has_permission(COMMISSIONING, "create", throw=True)
	return _start_rows(system_type)


def _start_rows(system_type: str | None) -> dict:
	tpl = template(system_type)
	return {
		"checklist": [{"item": _text(r, "item")} for r in tpl.get("checklist") or []],
		"readings": [{"param": _text(r, "param"), "unit": r.get("unit")} for r in tpl.get("readings") or []],
	}


@frappe.whitelist()
def item_warranty_months(item_code: str) -> int:
	if not item_code:
		return 0
	years, days = frappe.db.get_value("Item", item_code, ["sp_warranty_years", "warranty_period"]) or (0, 0)
	if flt(years):
		return cint(flt(years) * MONTHS_PER_YEAR)
	return cint(round(flt(days) / DAYS_PER_MONTH))


# --- the document -------------------------------------------------------------------------------


def validate(doc) -> None:
	station = frappe.db.get_value(STATION, doc.station, ["status"], as_dict=True)
	if not station:
		frappe.throw(_("Station {0} not found.").format(doc.station))
	if station.status == CANCELLED_STATION:
		frappe.throw(_("Station {0} is cancelled.").format(frappe.bold(doc.station)))
	_check_system(doc)
	if doc.is_new() and not doc.checklist and not doc.readings:
		start = _start_rows(doc.system_type)
		doc.set("checklist", start["checklist"])
		doc.set("readings", start["readings"])
	if doc.inverter_brand and frappe.db.get_value(LIST_VALUE, doc.inverter_brand, "list_name") != BRAND_LIST:
		frappe.throw(_("{0} is not an inverter brand.").format(frappe.bold(doc.inverter_brand)))
	doc.inverter_model = (doc.inverter_model or "").strip()
	if doc.settings_file:
		brand, model = frappe.db.get_value(SETTINGS_FILE, doc.settings_file, ["brand", "model"]) or (
			None,
			None,
		)
		if (brand, (model or "").lower()) != (doc.inverter_brand, doc.inverter_model.lower()):
			frappe.throw(
				_("Settings file {0} is not for this inverter brand and model.").format(
					frappe.bold(doc.settings_file)
				)
			)
	for row in doc.components:
		if not cint(row.warranty_months) and row.item:
			row.warranty_months = item_warranty_months(row.item)


def _check_system(doc) -> None:
	rows = {
		r.name: r.system_type
		for r in frappe.get_all(
			"SP Station System", {"parent": doc.station, "parenttype": STATION}, ["name", "system_type"]
		)
	}
	if rows and not doc.system_row:
		frappe.throw(_("Choose which of the station's systems this commissioning is for."))
	if doc.system_row and doc.system_row not in rows:
		frappe.throw(_("That system is not on station {0}.").format(frappe.bold(doc.station)))
	doc.system_type = rows.get(doc.system_row) if doc.system_row else None
	other = frappe.db.get_value(
		COMMISSIONING,
		{
			"station": doc.station,
			"system_row": doc.system_row or ("is", "not set"),
			"docstatus": ("!=", CANCELLED_DOC),
			"name": ("!=", doc.name),
		},
	)
	if other:
		frappe.throw(
			_("This system is already commissioned in {0}.").format(
				frappe.utils.get_link_to_form(COMMISSIONING, other)
			),
			frappe.DuplicateEntryError,
		)


def before_submit(doc) -> None:
	missing = [row.item for row in doc.checklist if not cint(row.done)]
	if missing:
		frappe.throw(
			_("Not done yet: {0}").format(", ".join(frappe.bold(m) for m in missing)),
			title=_("Checklist"),
		)
	for row in doc.components:
		row.warranty_end = warranty_end(doc.operation_date, row.warranty_months)


def warranty_end(operation_date, months) -> str | None:
	"""15-04-2027 + 24 months -> 14-04-2029."""
	if not operation_date or not cint(months):
		return None
	return str(add_days(add_months(getdate(operation_date), cint(months)), -1))


def on_submit(doc) -> None:
	_set_operation_date(doc.station)
	if _all_commissioned(doc.station):
		create_task(
			TECH_CLOSE_TASK,
			STATION,
			doc.station,
			_project_managers(),
			_("Close station {0} technically: operation date {1}").format(
				doc.station, frappe.utils.formatdate(_operation_date(doc.station))
			),
		)


def before_cancel(doc) -> None:
	status = frappe.db.get_value(STATION, doc.station, "status")
	if status in CLOSED_STATIONS and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Station {0} is closed; only the admin cancels its commissioning.").format(doc.station)
		)


def on_cancel(doc) -> None:
	_set_operation_date(doc.station)
	close_tasks(STATION, doc.station, TECH_CLOSE_TASK, status="Cancelled")


def _operation_date(station: str):
	dates = frappe.get_all(COMMISSIONING, {"station": station, "docstatus": 1}, pluck="operation_date")
	return max(dates) if dates else None


def _set_operation_date(station: str) -> None:
	frappe.db.set_value(STATION, station, "operation_date", _operation_date(station))


def _all_commissioned(station: str) -> bool:
	rows = set(frappe.get_all("SP Station System", {"parent": station, "parenttype": STATION}, pluck="name"))
	done = set(frappe.get_all(COMMISSIONING, {"station": station, "docstatus": 1}, pluck="system_row"))
	return rows <= done if rows else bool(done)


def _project_managers() -> list[str]:
	users = frappe.get_all("Has Role", {"role": PROJECT_MANAGER_ROLE, "parenttype": "User"}, pluck="parent")
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")
