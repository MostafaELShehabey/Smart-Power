"""Item import from Excel with Arabic headers (SP-29, I1).

One row per item. A code that already exists updates that item (blank cells keep the old
value); a new code creates it. Each row either saves or shows its own error, and one bad
row never stops the others. Brands and item groups must already exist: a typo such as
"PM TECH" vs "بي ام تك" is reported, not turned into a second brand (cleaning those is
SP-165's job).
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt
from frappe.utils.xlsxutils import build_xlsx_response, read_xlsx_file_from_attached_file

# (fieldname, Arabic header, English header, is_number)
COLUMNS = (
	("item_code", "الكود", "Item Code", False),
	("sp_name_ar", "الاسم العربي", "Arabic Name", False),
	("item_name", "الاسم بالإنجليزي", "Item Name", False),
	("item_group", "المجموعة", "Item Group", False),
	("brand", "الماركة", "Brand", False),
	("stock_uom", "الوحدة", "UOM", False),
	("sp_main_supplier", "المورد الرئيسي", "Main Supplier", False),
	("description", "الوصف", "Description", False),
	("sp_watt", "القدرة (وات)", "Power (W)", True),
	("sp_vmp", "Vmp", "Vmp (V)", True),
	("sp_voc", "Voc", "Voc (V)", True),
	("sp_imp", "Imp", "Imp (A)", True),
	("sp_isc", "Isc", "Isc (A)", True),
	("sp_kw", "القدرة (كيلووات)", "Power (kW)", True),
	("sp_max_dc_v", "أقصى جهد DC", "Max DC Voltage (V)", True),
	("sp_mppt_min", "أدنى MPPT", "MPPT Min (V)", True),
	("sp_mppt_max", "أقصى MPPT", "MPPT Max (V)", True),
	("sp_hp", "القدرة (حصان)", "Power (HP)", True),
	("sp_head_m", "الرفع (متر)", "Head (m)", True),
	("sp_flow_m3h", "التصرف (م³/ساعة)", "Flow (m³/h)", True),
	("sp_battery_ah", "سعة البطارية (أمبير ساعة)", "Battery Capacity (Ah)", True),
	("sp_system_voltage", "جهد النظام (فولت)", "System Voltage (V)", True),
)
HEADER_TO_FIELD = {
	header.strip().lower(): fieldname
	for fieldname, ar, en, _number in COLUMNS
	for header in (ar, en, fieldname)
}
NUMBER_FIELDS = {fieldname for fieldname, _ar, _en, number in COLUMNS if number}
TEMPLATE_NAME = "sp-items-template"
CREATED, UPDATED, ERROR = "Created", "Updated", "Error"


@frappe.whitelist()
def get_import_template():
	"""Download the Excel template: one header row in Arabic."""
	frappe.has_permission("Item", "create", throw=True)
	build_xlsx_response([[ar for _f, ar, _en, _n in COLUMNS]], TEMPLATE_NAME)


@frappe.whitelist(methods=["POST"])
def import_items(file_url: str) -> dict:
	"""Import an uploaded .xlsx file. Returns counts and one result per row."""
	frappe.has_permission("Item", "create", throw=True)
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	file_doc.check_permission("read")
	rows = read_xlsx_file_from_attached_file(fcontent=file_doc.get_content()) or []
	return import_rows(rows)


def import_rows(rows: list[list]) -> dict:
	"""rows[0] is the header row; the rest are items. Spreadsheet row numbers in results."""
	if not rows:
		frappe.throw(_("The file is empty."))
	fields = [HEADER_TO_FIELD.get(cstr(h).strip().lower()) for h in rows[0]]
	if "item_code" not in fields:
		frappe.throw(_("The file has no code column (الكود / Item Code)."))

	results, seen = [], {}
	for excel_row, values in enumerate(rows[1:], start=2):  # sp-allow-number: row 1 is the header
		data = {f: v for f, v in zip(fields, values, strict=False) if f and cstr(v).strip() != ""}
		if not data:
			continue
		results.append(_import_one(excel_row, data, seen))

	return {
		"created": sum(r["status"] == CREATED for r in results),
		"updated": sum(r["status"] == UPDATED for r in results),
		"errors": sum(r["status"] == ERROR for r in results),
		"rows": results,
	}


def _import_one(excel_row: int, data: dict, seen: dict) -> dict:
	code = cstr(data.get("item_code")).strip()
	result = {"row": excel_row, "item_code": code}
	if not code:
		return {**result, "status": ERROR, "message": _("The code is empty.")}
	if code in seen:
		return {
			**result,
			"status": ERROR,
			"message": _("Code {0} is repeated: it is already in row {1}.").format(code, seen[code]),
		}
	seen[code] = excel_row

	values = {f: (flt(v) if f in NUMBER_FIELDS else cstr(v).strip()) for f, v in data.items()}
	frappe.db.savepoint("sp_item_import_row")
	try:
		for fieldname, doctype in (("brand", "Brand"), ("item_group", "Item Group")):
			if values.get(fieldname) and not frappe.db.exists(doctype, values[fieldname]):
				frappe.throw(_("{0} {1} does not exist.").format(_(doctype), values[fieldname]))
		if frappe.db.exists("Item", code):
			doc = frappe.get_doc("Item", code)
			doc.update({k: v for k, v in values.items() if k != "item_code"})
			doc.save()
			status = UPDATED
		else:
			values.setdefault("item_name", values.get("sp_name_ar") or code)
			doc = frappe.get_doc({"doctype": "Item", **values}).insert()
			status = CREATED
		return {**result, "status": status, "message": ""}
	except Exception as e:
		frappe.db.rollback(save_point="sp_item_import_row")
		frappe.clear_messages()
		return {**result, "status": ERROR, "message": cstr(e) or e.__class__.__name__}
