"""Workers (SP-159): names, mobiles, wages, as Employees (SP-33).

    template(out)            the workers template
    run(path, dry_run=1)     the filled template

A worker is matched by mobile, else by name. A daily worker has a daily wage; a salaried one a
monthly salary. A match gets only what it lacks.
"""

import frappe
from frappe import _
from frappe.utils import flt

from smart_power.migration import common
from smart_power.sp_sales.customer import is_valid_mobile, normalize_mobile

KIND = "workers"
COLUMNS = (
	("name", "الاسم", "name"),
	("mobile", "الموبايل", "mobile"),
	("daily", "عامل يومية", "daily worker"),
	("daily_wage", "اليومية", "daily wage"),
	("monthly_salary", "المرتب الشهري", "monthly salary"),
	("skill", "المهارة", "skill"),
	("joined_on", "تاريخ الالتحاق", "date of joining"),
)
SKILL_LIST = "Worker Skill"


def template(out: str) -> str:
	return common.template(COLUMNS, out)


def run(path: str, dry_run: int = 1, company: str | None = None, report: str | None = None) -> dict:
	result = common.start(KIND, path, dry_run)
	company = company or frappe.db.get_single_value("Global Defaults", "default_company")
	rows = common.read(path, COLUMNS)
	result.source_rows = len(rows)
	items, seen = [], {}
	for row in rows:
		given = str(row.get("mobile") or "").strip()
		mobile = normalize_mobile(given)
		row["mobile"] = mobile if is_valid_mobile(mobile) else None
		row["_key"] = row["mobile"] or common.key(row.get("name"))
		if not row.get("name"):
			result.add(row, common.ERROR, None, _("No name."))
		elif given and not row["mobile"]:
			result.add(row, common.ERROR, None, _("{0} is not a valid mobile.").format(given))
		elif row["_key"] in seen:
			result.add(row, common.SKIPPED, None, _("Repeats row {0}.").format(seen[row["_key"]]))
		else:
			seen[row["_key"]] = row["_row"]
			items.append(row)
	common.run_rows(result, items, lambda row: _save(row, company))
	return common.finish(result, report)


def _save(row: dict, company: str) -> tuple:
	skill = common.list_value(SKILL_LIST, row.get("skill"))
	if row.get("skill") and not skill:
		frappe.throw(_("{0} is not in the Worker Skill list.").format(row.get("skill")))
	daily = common.yes(row.get("daily")) or (flt(row.get("daily_wage")) > 0 and not row.get("monthly_salary"))
	values = {
		"cell_number": row.get("mobile"),
		"sp_daily_wage": flt(row.get("daily_wage")) or None,
		"sp_monthly_salary": flt(row.get("monthly_salary")) or None,
		"sp_skill": skill,
	}
	existing = (row.get("mobile") and frappe.db.get_value("Employee", {"cell_number": row["mobile"]})) or (
		frappe.db.get_value("Employee", {"employee_name": row["name"], "company": company})
	)
	if existing:
		doc = frappe.get_doc("Employee", existing)
		if not common.fill(doc, values):
			return common.UNCHANGED, doc.name, ""
		doc.flags.ignore_permissions = True
		doc.save()
		return common.UPDATED, doc.name, ""
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": row["name"],
			"company": company,
			"status": "Active",
			"sp_is_daily_worker": 1 if daily else 0,
			**({"date_of_joining": row["joined_on"]} if row.get("joined_on") else {}),
			**{k: v for k, v in values.items() if v},
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return common.CREATED, doc.name, ""
