"""Suppliers (SP-159): with their payment terms; the consignment owner (Africa System) flagged.

    template(out)            the suppliers template
    run(path, dry_run=1)     the filled template

A supplier is matched by its name or any spelling in its Other Spellings (SP-165), so «PM TECH»
and «بي ام تك» are one supplier. A match gets only what it lacks (and the consignment flag); a
new name is created.
"""

import frappe
from frappe import _

from smart_power.migration import common
from smart_power.sp_stock.item_codes import _index

KIND = "suppliers"
COLUMNS = (
	("supplier_name", "المورد", "supplier"),
	("supplier_group", "مجموعة الموردين", "supplier group"),
	("mobile", "الموبايل", "mobile"),
	("whatsapp", "واتساب", "whatsapp"),
	("payment_terms", "شروط الدفع", "payment terms"),
	("terms_note", "ملاحظات الشروط", "terms note"),
	("consignment", "يترك بضاعة أمانة", "consignment owner"),
	("aliases", "طرق كتابة أخرى", "other spellings"),
)
ROOT_GROUP = "All Supplier Groups"


def template(out: str) -> str:
	return common.template(COLUMNS, out)


def run(path: str, dry_run: int = 1, report: str | None = None) -> dict:
	result = common.start(KIND, path, dry_run)
	rows = common.read(path, COLUMNS)
	result.source_rows = len(rows)
	index, seen = _index("Supplier"), {}
	items = []
	for row in rows:
		row["_key"] = common.key(row.get("supplier_name"))
		if not row["_key"]:
			result.add(row, common.ERROR, None, _("No supplier name."))
		elif row["_key"] in seen:
			result.add(row, common.SKIPPED, None, _("Repeats row {0}.").format(seen[row["_key"]]))
		else:
			seen[row["_key"]] = row["_row"]
			items.append(row)
	common.run_rows(result, items, lambda row: _save(row, index))
	return common.finish(result, report)


def _values(row: dict) -> dict:
	terms = row.get("payment_terms")
	if terms and not frappe.db.exists("Payment Terms Template", terms):
		frappe.throw(_("Payment terms {0} are not found.").format(terms))
	group = row.get("supplier_group")
	if group and not frappe.db.exists("Supplier Group", group):
		frappe.throw(_("Supplier group {0} is not found.").format(group))
	return {
		"supplier_group": group,
		"mobile_no": row.get("mobile"),
		"sp_whatsapp": row.get("whatsapp"),
		"payment_terms": terms,
		"sp_terms_note": row.get("terms_note"),
		"sp_aliases": row.get("aliases"),
	}


def _save(row: dict, index: dict) -> tuple:
	values = _values(row)
	consignment = common.yes(row.get("consignment"))
	existing = index.get(row["_key"])
	if existing:
		doc = frappe.get_doc("Supplier", existing)
		changed = common.fill(doc, values)
		if consignment and not doc.sp_is_consignment_owner:
			doc.sp_is_consignment_owner, changed = 1, True
		if not changed:
			return common.UNCHANGED, doc.name, ""
		doc.flags.ignore_permissions = True
		doc.save()
		return common.UPDATED, doc.name, ""
	default_group = frappe.db.get_single_value("Buying Settings", "supplier_group") or ROOT_GROUP
	doc = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": row["supplier_name"],
			**{k: v for k, v in values.items() if v},
			"supplier_group": values["supplier_group"] or default_group,
			"sp_is_consignment_owner": 1 if consignment else 0,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	index[row["_key"]] = doc.name
	return common.CREATED, doc.name, ""
