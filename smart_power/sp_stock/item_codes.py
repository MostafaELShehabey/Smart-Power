"""Item coding scheme, per-group import template and cleansing (SP-165).

    code = GROUP-BRAND-MODEL      e.g. PNL-JA-625, INV-SANCH-110HP, PMP-FERAT-SP110-09

- GROUP is the item group's Code Prefix, BRAND the brand's Code, MODEL the model without spaces,
  in capitals. The item group also lists the specs every item of the group must have.
- The template is one Excel sheet per item group: the item columns, that group's required spec
  columns, and the supplier price columns (supplier, price date, prices).
- Cleansing, before anything is saved: spacing is normalised; brand and supplier spellings are
  mapped to the one record (its name, its Other Spellings, or the same letters ignoring spaces,
  case and Arabic letter forms, so PM TECH, PMTECH and بي ام تك land on one supplier); every row
  gets its code; a code seen twice (two spellings of one item) is reported and only the first is
  created; missing group specs, a missing UOM, and a price without a supplier or a date are
  reported. Only clean rows are imported, through the item (SP-29) and price (SP-30) imports.
"""

import re

import frappe
from frappe import _
from frappe.utils import cstr, flt
from frappe.utils.xlsxutils import build_xlsx_response, read_xlsx_file_from_attached_file

from smart_power.permissions import can_see_cost
from smart_power.sp_core.setup.seed import defaults
from smart_power.sp_stock import item_import, price_import
from smart_power.sp_stock.prices import BTB, BTC, COST, COST_SIDE, LIST

OK, DUPLICATE, ERROR = "OK", "Duplicate", "Error"
SPEC_LABELS = {f: (ar, en) for f, ar, en, number in item_import.COLUMNS if number}
# (key, Arabic header, English header)
ITEM_COLUMNS = (
	("item_code", "الكود", "Item Code"),
	("sp_model", "الموديل", "Model"),
	("sp_name_ar", "الاسم العربي", "Arabic Name"),
	("item_name", "الاسم بالإنجليزي", "Item Name"),
	("brand", "الماركة", "Brand"),
	("stock_uom", "الوحدة", "UOM"),
	("sp_main_supplier", "المورد الرئيسي", "Main Supplier"),
	("description", "الوصف", "Description"),
)
PRICE_COLUMNS = (
	("supplier", "المورد", "Supplier"),
	("price_date", "تاريخ السعر", "Price Date"),
	(LIST, "سعر اللستة", "List Price"),
	(COST, "تكلفة P1", "P1 Cost"),
	(BTB, "سعر الشركات BTB", "BTB"),
	(BTC, "سعر العميل BTC", "BTC"),
)
PRICE_FIELDS = (LIST, COST, BTB, BTC)
ITEM_FIELDS = {c[0] for c in ITEM_COLUMNS} | set(SPEC_LABELS)
# one form of each Arabic letter for matching spellings (the letters are meant)
ARABIC_FORMS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ـ": ""})  # noqa: RUF001


# --- the scheme ------------------------------------------------------------------------------------


def _ensure_group_fields() -> None:
	"""The Item Group fields from the fixtures, when a patch runs before the fixtures sync."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	if frappe.db.has_column("Item Group", "sp_code_prefix") and frappe.db.has_column(
		"Item Group", "sp_required_specs"
	):
		return
	fixture = frappe.get_file_json(frappe.get_app_path("smart_power", "fixtures", "custom_field.json"))
	for row in fixture:
		if row["dt"] == "Item Group" and not frappe.db.exists("Custom Field", row["name"]):
			create_custom_field(
				"Item Group", {k: v for k, v in row.items() if k not in ("doctype", "name", "dt")}
			)


def seed_group_codes() -> None:
	"""The code prefix and required specs of the catalogue groups, where they are still empty."""
	_ensure_group_fields()
	for name, spec in defaults()["item_groups"].get("codes", {}).items():
		if not frappe.db.exists("Item Group", name):
			continue
		values = {}
		if not frappe.db.get_value("Item Group", name, "sp_code_prefix"):
			values["sp_code_prefix"] = spec["prefix"]
		if not frappe.db.get_value("Item Group", name, "sp_required_specs") and spec["specs"]:
			values["sp_required_specs"] = ", ".join(spec["specs"])
		if values:
			frappe.db.set_value("Item Group", name, values)


def spaces(value) -> str:
	"""Trimmed, with single spaces."""
	return re.sub(r"\s+", " ", cstr(value)).strip()


def key(value) -> str:
	"""For matching spellings: no spaces or dashes, one case, one form of each Arabic letter."""
	return re.sub(r"[\s\-_.]+", "", spaces(value).translate(ARABIC_FORMS)).casefold()


def model_part(model) -> str:
	return re.sub(r"[^A-Z0-9.\-]+", "", spaces(model).upper().replace(" ", ""))


def make_code(item_group: str, brand: str, model: str) -> str | None:
	prefix = frappe.db.get_value("Item Group", item_group, "sp_code_prefix")
	brand_code = frappe.db.get_value("Brand", brand, "sp_code") if brand else None
	model = model_part(model)
	if not (prefix and brand_code and model):
		return None
	return f"{prefix.strip().upper()}-{brand_code.strip().upper()}-{model}"


def required_specs(item_group: str) -> list[str]:
	text = frappe.db.get_value("Item Group", item_group, "sp_required_specs") or ""
	return [f.strip() for f in text.split(",") if f.strip() in SPEC_LABELS]


def _index(doctype: str) -> dict:
	"""Every way a brand or supplier is written -> its record."""
	alias_field = "sp_aliases"
	index = {}
	for row in frappe.get_all(doctype, fields=["name", alias_field]):
		for spelling in [row.name, *cstr(row.get(alias_field)).split(",")]:
			if spelling.strip():
				index.setdefault(key(spelling), row.name)
	return index


# --- the template ----------------------------------------------------------------------------------


def template_columns(item_group: str) -> list[tuple]:
	cost = can_see_cost()
	specs = [(f, *SPEC_LABELS[f]) for f in required_specs(item_group)]
	prices = [c for c in PRICE_COLUMNS if cost or c[0] not in COST_SIDE]
	return [*ITEM_COLUMNS, *specs, *prices]


@frappe.whitelist()
def get_group_template(item_group: str):
	"""The Excel template of one item group: item columns, its required specs, supplier prices."""
	frappe.has_permission("Item", "create", throw=True)
	if not frappe.db.exists("Item Group", item_group):
		frappe.throw(_("Item group {0} does not exist.").format(item_group))
	header = [ar for _f, ar, _en in template_columns(item_group)]
	prefix = frappe.db.get_value("Item Group", item_group, "sp_code_prefix") or "items"
	build_xlsx_response([header], f"sp-{prefix.lower()}-template")


# --- cleansing --------------------------------------------------------------------------------------


def check_rows(rows: list[list], item_group: str) -> list[dict]:
	"""rows[0] is the header. Each row comes back cleaned, with its code, status and messages."""
	if not rows:
		frappe.throw(_("The file is empty."))
	columns = template_columns(item_group) + [c for c in PRICE_COLUMNS if c[0] in COST_SIDE]
	by_header = {h.strip().lower(): f for f, ar, en in columns for h in (ar, en, f)}
	fields = [by_header.get(spaces(h).lower()) for h in rows[0]]
	brands, suppliers = _index("Brand"), _index("Supplier")
	specs = required_specs(item_group)
	seen, out = {}, []
	for excel_row, values in enumerate(rows[1:], start=2):  # sp-allow-number: row 1 is the header
		data = {f: v for f, v in zip(fields, values, strict=False) if f and cstr(v).strip() != ""}
		if not data:
			continue
		messages = []
		for f, v in list(data.items()):
			if f not in PRICE_FIELDS and f not in SPEC_LABELS and f != "price_date":
				data[f] = spaces(v)
		for field, index, doctype in (
			("brand", brands, "Brand"),
			("sp_main_supplier", suppliers, "Supplier"),
			("supplier", suppliers, "Supplier"),
		):
			if data.get(field):
				found = index.get(key(data[field]))
				if found:
					data[field] = found
				else:
					messages.append(
						_("{0} {1} is not known; add it or one of its spellings first.").format(
							_(doctype), data[field]
						)
					)
		code = data.get("item_code") or (
			make_code(item_group, data.get("brand"), data.get("sp_model")) if data.get("brand") else None
		)
		if not code:
			messages.append(_("No code: fill the code, or the brand (with a Code) and the model."))
		else:
			data["item_code"] = code
		exists = bool(code) and frappe.db.exists("Item", code)
		if not data.get("stock_uom") and not exists:
			messages.append(_("The UOM is missing."))
		missing = [
			_(SPEC_LABELS[f][1])
			for f in specs
			if not flt(data.get(f)) and not (exists and frappe.db.get_value("Item", code, f))
		]
		if missing:
			messages.append(_("Missing specs for this group: {0}.").format(", ".join(missing)))
		if any(f in data for f in PRICE_FIELDS):
			if not data.get("supplier"):
				messages.append(_("A price needs its supplier."))
			if not data.get("price_date"):
				messages.append(_("A price needs its date."))
		status = ERROR if messages else OK
		if code and code in seen:
			status = DUPLICATE
			messages = [_("Same item as row {0} ({1}): only that row is imported.").format(seen[code], code)]
		elif code:
			seen[code] = excel_row
		out.append(
			{"row": excel_row, "item_code": code, "status": status, "messages": messages, "data": data}
		)
	return out


@frappe.whitelist(methods=["POST"])
def import_group(file_url: str, item_group: str, dry_run: int = 1) -> dict:
	"""Check the filled template (dry run), or import its clean rows: items, then their prices."""
	frappe.has_permission("Item", "create", throw=True)
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	file_doc.check_permission("read")
	rows = read_xlsx_file_from_attached_file(fcontent=file_doc.get_content()) or []
	return import_checked(rows, item_group, int(dry_run), source=file_doc.file_name)


def import_checked(rows: list[list], item_group: str, dry_run: int = 1, source: str = "") -> dict:
	checked = check_rows(rows, item_group)
	result = {
		"ok": sum(r["status"] == OK for r in checked),
		"duplicates": sum(r["status"] == DUPLICATE for r in checked),
		"errors": sum(r["status"] == ERROR for r in checked),
		"rows": [{k: r[k] for k in ("row", "item_code", "status", "messages")} for r in checked],
		"imported": 0,
	}
	if dry_run:
		return result
	day_first = (frappe.db.get_single_value("System Settings", "date_format") or "").startswith("dd")
	reason = _("Import: {0}").format(source) if source else _("Import")
	item_seen, price_seen = {}, {}
	for r in checked:
		if r["status"] != OK:
			continue
		data = r["data"]
		item = {f: v for f, v in data.items() if f in ITEM_FIELDS}
		item["item_group"] = item_group
		done = item_import._import_one(r["row"], item, item_seen)
		if done["status"] == item_import.ERROR:
			r["status"], r["messages"] = ERROR, [done["message"]]
			continue
		prices = {f: data[f] for f in ("item_code", "supplier", "price_date", *PRICE_FIELDS) if f in data}
		if any(f in prices for f in PRICE_FIELDS):
			if any(f in prices for f in COST_SIDE) and not can_see_cost():
				prices = {f: v for f, v in prices.items() if f not in COST_SIDE}
			saved = price_import._import_one(r["row"], prices, price_seen, reason, day_first, 1)
			if saved["status"] == price_import.ERROR:
				r["messages"] = [_("Item saved, but its price was not: {0}").format(saved["message"])]
		result["imported"] += 1
	result["rows"] = [{k: r[k] for k in ("row", "item_code", "status", "messages")} for r in checked]
	result["errors"] = sum(r["status"] == ERROR for r in checked)
	return result
