"""Price import from Excel with Arabic headers (SP-30, I2).

One row per item and supplier: List Price, P1 Cost, BTB, BTC, the price date and the
supplier. The prices are upserted by item code (and supplier for buying prices): a blank
cell keeps the old price, and a changed price is logged with the reason "Import: <file>".
An empty date means today, so re-importing a price fixes a stale date (the motors and pumps
in the old sheet kept their 2025 dates after their prices changed).

Each row either saves or shows its own error, and one bad row never stops the others. Items
must already exist (the item import is SP-29). List Price and P1 Cost columns are refused
for users without cost access (SP-35). After a row's prices are in, the category's pricing
rules run, unless the import is told not to.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate
from frappe.utils.xlsxutils import build_xlsx_response, read_xlsx_file_from_attached_file

from smart_power.permissions import can_see_cost
from smart_power.sp_stock import prices
from smart_power.sp_stock.prices import BTB, BTC, COST, COST_SIDE, LIST

# (fieldname, Arabic header, English header)
COLUMNS = (
	("item_code", "الكود", "Item Code"),
	("supplier", "المورد", "Supplier"),
	("price_date", "تاريخ السعر", "Price Date"),
	(LIST, "سعر اللستة", "List Price"),
	(COST, "تكلفة P1", "P1 Cost"),
	(BTB, "سعر الشركات BTB", "BTB"),
	(BTC, "سعر العميل BTC", "BTC"),
)
HEADER_TO_FIELD = {
	header.strip().lower(): fieldname for fieldname, ar, en in COLUMNS for header in (ar, en, fieldname)
}
PRICE_FIELDS = (LIST, COST, BTB, BTC)
TEMPLATE_NAME = "sp-prices-template"
SAVED, UNCHANGED, ERROR = "Saved", "Unchanged", "Error"


@frappe.whitelist()
def get_import_template():
	"""Download the Excel template: one header row in Arabic (cost columns for cost roles only)."""
	frappe.has_permission("Item Price", "write", throw=True)
	columns = [c for c in COLUMNS if can_see_cost() or c[0] not in COST_SIDE]
	build_xlsx_response([[ar for _f, ar, _en in columns]], TEMPLATE_NAME)


@frappe.whitelist(methods=["POST"])
def import_prices(file_url: str, apply_rules: int = 1) -> dict:
	"""Import an uploaded .xlsx file. Returns counts and one result per row."""
	frappe.has_permission("Item Price", "write", throw=True)
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	file_doc.check_permission("read")
	rows = read_xlsx_file_from_attached_file(fcontent=file_doc.get_content()) or []
	return import_rows(rows, source=file_doc.file_name, apply_rules=cint(apply_rules))


def import_rows(rows: list[list], source: str = "", apply_rules: int = 1) -> dict:
	"""rows[0] is the header row. Results use spreadsheet row numbers."""
	if not rows:
		frappe.throw(_("The file is empty."))
	fields = [HEADER_TO_FIELD.get(cstr(h).strip().lower()) for h in rows[0]]
	if "item_code" not in fields:
		frappe.throw(_("The file has no code column (الكود / Item Code)."))
	if not any(f in PRICE_FIELDS for f in fields):
		frappe.throw(_("The file has no price column."))
	if any(f in COST_SIDE for f in fields) and not can_see_cost():
		frappe.throw(
			_("You cannot import cost prices. Remove the List Price and P1 Cost columns."),
			frappe.PermissionError,
		)

	reason = _("Import: {0}").format(source) if source else _("Import")
	day_first = (frappe.db.get_single_value("System Settings", "date_format") or "").startswith("dd")
	results, seen = [], {}
	for excel_row, values in enumerate(rows[1:], start=2):  # sp-allow-number: row 1 is the header
		data = {f: v for f, v in zip(fields, values, strict=False) if f and cstr(v).strip() != ""}
		if not data:
			continue
		results.append(_import_one(excel_row, data, seen, reason, day_first, apply_rules))

	return {
		"saved": sum(r["status"] == SAVED for r in results),
		"unchanged": sum(r["status"] == UNCHANGED for r in results),
		"errors": sum(r["status"] == ERROR for r in results),
		"rows": results,
	}


def _import_one(
	excel_row: int, data: dict, seen: dict, reason: str, day_first: bool, apply_rules: int
) -> dict:
	code = cstr(data.get("item_code")).strip()
	supplier = cstr(data.get("supplier")).strip() or None
	result = {"row": excel_row, "item_code": code}
	if not code:
		return {**result, "status": ERROR, "message": _("The code is empty.")}
	key = (code, supplier)
	if key in seen:
		return {
			**result,
			"status": ERROR,
			"message": _("{0} is repeated: it is already in row {1}.").format(code, seen[key]),
		}
	seen[key] = excel_row

	frappe.db.savepoint("sp_price_import_row")
	try:
		if not frappe.db.exists("Item", code):
			frappe.throw(_("Item {0} does not exist. Import it first.").format(code))
		if supplier and not frappe.db.exists("Supplier", supplier):
			frappe.throw(_("Supplier {0} does not exist.").format(supplier))
		price_date = _date(data.get("price_date"), day_first)
		given, changed = {}, False
		for field in PRICE_FIELDS:
			if field not in data:
				continue
			rate = flt(data[field])
			if rate < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(prices.price_list_label(field))))
			given[field] = rate
			_name, did_change = prices.set_price(
				code,
				field,
				rate,
				supplier=supplier if field in COST_SIDE else None,
				price_date=price_date,
				reason=reason,
			)
			changed = changed or did_change
		if not given:
			frappe.throw(_("The row has no price."))
		if apply_rules:
			derived = prices.apply_category_rules(code, reason=reason, price_date=price_date, given=given)
			changed = changed or bool(derived)
		return {**result, "status": SAVED if changed else UNCHANGED, "message": ""}
	except Exception as e:
		frappe.db.rollback(save_point="sp_price_import_row")
		frappe.clear_messages()
		return {**result, "status": ERROR, "message": cstr(e) or e.__class__.__name__}


def _date(value, day_first: bool):
	if value in (None, ""):
		return None
	if hasattr(value, "year"):
		return getdate(value)
	return getdate(cstr(value).strip(), parse_day_first=day_first)
