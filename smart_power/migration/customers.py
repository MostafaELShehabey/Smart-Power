"""Customers (SP-159): one customer per mobile.

    template(out)                      the customers template
    run(path, dry_run=1)               the filled template
    from_statement(path, dry_run=1)    the station customers of the yearly statement
                                       («كشف حساب»: one sheet per station, «محطة (n)»), featured

Mobiles are normalised to 01XXXXXXXXX. Rows that share a mobile are one customer: the first
row's name is kept and its blanks are filled from the later rows, which the report lists as
merged. A mobile that is already a customer updates that customer (only what it lacks, and
featured), so a second run changes nothing. A row with no valid mobile is an error: the
customer master needs one (SP-31).
"""

import re

import frappe
from frappe import _

from smart_power.migration import common
from smart_power.sp_sales.customer import find_by_mobile, is_valid_mobile, normalize_mobile

KIND = "customers"
COLUMNS = (
	("customer_name", "الاسم", "name"),
	("mobile", "الموبايل", "mobile"),
	("mobile_2", "موبايل آخر", "mobile 2"),
	("tier", "النوع (فرد / شركة)", "tier"),
	("region", "المنطقة", "region"),
	("featured", "مميز", "featured"),
	("owner", "مسؤول المتابعة", "owner"),
)
TIERS = {
	common.key(spelling): tier
	for tier, spellings in (
		("Individual", ("فرد", "individual", "btc")),
		("Company", ("شركة", "company", "btb")),
	)
	for spelling in spellings
}
REGION_LIST = "Region"
STATION_SHEET = "محطة"
NAME_LABEL, PHONE_LABEL = "العميل", "رقم التليفون"
LABEL_ROWS = 12  # sp-allow-number: the station sheet's heading block
LOCAL_DIGITS = 11  # sp-allow-number: 01XXXXXXXXX
MOBILE_DIGITS = re.compile(r"\+?\d[\d ]{9,15}")


def template(out: str) -> str:
	return common.template(COLUMNS, out)


def run(path: str, dry_run: int = 1, report: str | None = None) -> dict:
	result = common.start(KIND, path, dry_run)
	rows = common.read(path, COLUMNS)
	return _load(result, rows, report)


def from_statement(path: str, dry_run: int = 1, report: str | None = None) -> dict:
	result = common.start(f"{KIND}-statement", path, dry_run)
	return _load(result, statement_rows(path), report)


def statement_rows(path: str) -> list[dict]:
	"""Each station sheet's customer: the name and phone beside their labels, featured."""
	rows = []
	for title, cells in common._workbook_rows(path).items():
		if not title.strip().startswith(STATION_SHEET):
			continue
		found = {"_sheet": title, "featured": 1, "_row": None}
		for number, values in enumerate(cells[:LABEL_ROWS], start=1):
			labels = [common.spaces(v) if v is not None else "" for v in values]
			for i, label in enumerate(labels):
				value = next((v for v in labels[i + 1 :] if v), "")
				if label == NAME_LABEL and "customer_name" not in found:
					found.update(customer_name=value, _row=number)
				elif label.startswith(PHONE_LABEL) and "mobile" not in found:
					# the number may sit in the label's own cell («رقم التليفون 01…»)
					mobiles = mobiles_in(f"{label} {value}")
					found.update(
						mobile=mobiles[0] if mobiles else value, mobile_2=next(iter(mobiles[1:]), None)
					)
		if found.get("customer_name"):
			rows.append(found)
	return rows


def mobiles_in(text) -> list[str]:
	"""The valid mobiles in a cell that may hold two («010… / 011…»). Excel keeps a mobile typed
	as a number without its leading 0 (1001234567), so it is put back."""
	found = []
	for match in MOBILE_DIGITS.findall(str(text or "")):
		digits = re.sub(r"\D", "", match)
		if len(digits) == LOCAL_DIGITS - 1 and digits.startswith("1"):
			digits = "0" + digits
		found.append(normalize_mobile(digits))
	return [m for m in found if is_valid_mobile(m)]


def _load(report: common.Report, rows: list[dict], out: str | None) -> dict:
	report.source_rows = len(rows)
	common.run_rows(report, _groups(report, rows), _save)
	return common.finish(report, out)


def _groups(report: common.Report, rows: list[dict]) -> list[dict]:
	"""One merged row per mobile; the rows merged into another are reported as merged."""
	groups: dict[str, dict] = {}
	for row in rows:
		mobile = normalize_mobile(str(row.get("mobile") or ""))
		row["_key"] = mobile
		if not row.get("customer_name"):
			report.add(row, common.ERROR, None, _("No name."))
			continue
		if not is_valid_mobile(mobile):
			report.add(row, common.ERROR, None, _("No valid mobile: add one, then run again."))
			continue
		row["mobile"] = mobile
		head = groups.get(mobile)
		if not head:
			groups[mobile] = row
			continue
		for field, value in row.items():
			if not field.startswith("_") and value not in (None, "") and head.get(field) in (None, ""):
				head[field] = value
		head["featured"] = 1 if common.yes(head.get("featured")) or common.yes(row.get("featured")) else 0
		where = head.get("_sheet") or _("row {0}").format(head.get("_row"))
		report.add(row, common.MERGED, None, _("Same mobile as {0}: merged into it.").format(where))
	return list(groups.values())


def _values(row: dict) -> dict:
	tier = row.get("tier")
	if tier and common.key(tier) not in TIERS:
		frappe.throw(_("Tier {0} is not فرد or شركة.").format(tier))
	region = common.list_value(REGION_LIST, row.get("region"))
	if row.get("region") and not region:
		frappe.throw(_("{0} is not in the Region list.").format(row.get("region")))
	owner = row.get("owner")
	owner_user = owner and (
		frappe.db.exists("User", owner) or frappe.db.get_value("User", {"full_name": owner, "enabled": 1})
	)
	if owner and not owner_user:
		frappe.throw(_("{0} is not a user.").format(owner))
	mobile_2 = normalize_mobile(str(row.get("mobile_2") or "")) or None
	return {
		"sp_mobile_2": mobile_2 if mobile_2 != row["mobile"] else None,
		"sp_tier": TIERS.get(common.key(tier)) if tier else None,
		"sp_region": region,
		"sp_owner_user": owner_user or None,
	}


def _save(row: dict) -> tuple:
	values = _values(row)
	featured = common.yes(row.get("featured"))
	existing = find_by_mobile(row["mobile"])
	if existing:
		doc = frappe.get_doc("Customer", existing)
		changed = common.fill(doc, values)
		if featured and not doc.sp_featured:
			doc.sp_featured, changed = 1, True
		if not changed:
			return common.UNCHANGED, doc.name, _("Already a customer.")
		doc.flags.ignore_permissions = True
		doc.save()
		return common.UPDATED, doc.name, _("Already a customer: what it lacked is filled in.")
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": row["customer_name"],
			"sp_mobile": row["mobile"],
			"sp_featured": 1 if featured else 0,
			**{k: v for k, v in values.items() if v},
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return common.CREATED, doc.name, ""
