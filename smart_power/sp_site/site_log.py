"""Site daily log (SP-96, SL1): one log per site per day; its labour and materials cost the station.

A log carries the crew (staff and daily workers: days, wage), the stages done (the X4 "Site Stage"
list), the materials used from the station's site warehouse, issues, a voice note and photos
(each photo can be marked usable for marketing, SP-53).

On submit:
- the materials leave the site warehouse as a Material Issue to "Project Materials" on the
  Projects center, with project = the station (the ERD 7.2 note: no extra dimension);
- the labour posts through the Account Map's "Site Labour" event: Dr "Project Labour" (the
  station's project) / Cr "Daily Wages Payable", or the custody account the wages were paid from.

Cancelling reverses both, within the field-entry lock window (decision 44, 3 days; the admin at
any time).

    station_cost(station)    the station's actual cost so far, from what posted to its project
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_link_to_form, getdate, now_datetime, today

from smart_power.sp_finance.centers import PROJECTS, center

LOG = "SP Site Daily Log"
EVENT = "Site Labour"
MATERIALS_ACCOUNT, LABOUR_ACCOUNT, WAGES_PAYABLE = (
	"Project Materials",
	"Project Labour",
	"Daily Wages Payable",
)
CLOSED = ("Financially closed", "Cancelled")
ADMIN_ROLES = ("SP Admin", "System Manager")
CUSTODY_KIND = "Custody"
CANCELLED = 2  # sp-allow-number: docstatus


def _account(company: str, account_name: str) -> str | None:
	return frappe.db.get_value("Account", {"company": company, "account_name": account_name, "is_group": 0})


def validate(doc) -> None:
	station = frappe.db.get_value(
		"SP Station", doc.station, ["status", "project", "site_warehouse", "company"], as_dict=True
	)
	if not station:
		frappe.throw(_("Choose the station."))
	if station.status in CLOSED:
		frappe.throw(
			_("Station {0} is {1}: it takes no more site logs.").format(doc.station, _(station.status))
		)
	doc.project, doc.site_warehouse, doc.company = station.project, station.site_warehouse, station.company
	if doc.is_new() and not doc.entry_time:
		doc.entry_time = now_datetime()
	_one_per_day(doc)
	_crew(doc)
	_materials(doc)
	_paid_from(doc)


def _one_per_day(doc) -> None:
	other = frappe.db.get_value(
		LOG,
		{
			"station": doc.station,
			"work_date": doc.work_date,
			"docstatus": ("<", CANCELLED),
			"name": ("!=", doc.name),
		},
	)
	if other:
		frappe.throw(
			_("Station {0} already has the log of {1}: {2}. Add to it instead.").format(
				doc.station, frappe.format(doc.work_date, "Date"), get_link_to_form(LOG, other)
			),
			frappe.DuplicateEntryError,
			title=_("One log per site per day"),
		)


def _crew(doc) -> None:
	seen = set()
	for row in doc.crew:
		if row.employee in seen:
			frappe.throw(
				_("Row {0}: {1} is already on the crew.").format(row.idx, row.employee_name or row.employee)
			)
		seen.add(row.employee)
		if flt(row.days) <= 0:
			frappe.throw(_("Row {0}: the days must be above zero.").format(row.idx))
		if not flt(row.wage):
			row.wage = flt(frappe.db.get_value("Employee", row.employee, "sp_daily_wage"))
		row.amount = flt(row.days) * flt(row.wage)
	doc.labour_total = sum(flt(r.amount) for r in doc.crew)


def _materials(doc) -> None:
	"""Only what the site holds, counting every row of the same item together."""
	wanted = {}
	for row in doc.materials:
		if flt(row.qty) <= 0:
			frappe.throw(_("Row {0}: the quantity must be above zero.").format(row.idx))
		wanted[row.item_code] = wanted.get(row.item_code, 0) + flt(row.qty)
		bin_ = (
			frappe.db.get_value(
				"Bin",
				{"item_code": row.item_code, "warehouse": doc.site_warehouse},
				["actual_qty", "valuation_rate"],
				as_dict=True,
			)
			or frappe._dict()
		)
		row.available_qty = flt(bin_.actual_qty)
		row.valuation_rate = flt(bin_.valuation_rate)
	if doc.docstatus == 1:
		return  # submitted: the stock has already left
	for row in doc.materials:
		if wanted[row.item_code] > flt(row.available_qty):
			frappe.throw(
				_("{0}: {1} used but the site holds {2}.").format(
					row.item_name or row.item_code, wanted[row.item_code], flt(row.available_qty)
				),
				title=_("More than the site holds"),
			)


def _paid_from(doc) -> None:
	if not doc.paid_from:
		return
	kind, company = frappe.db.get_value("Account", doc.paid_from, ["sp_account_kind", "company"])
	if kind != CUSTODY_KIND or company != doc.company:
		frappe.throw(_("Wages are paid from a custody account of the station's company."))


# --- posting ------------------------------------------------------------------------------------


def on_submit(doc) -> None:
	if doc.materials:
		doc.db_set("stock_entry", _issue(doc))
	if flt(doc.labour_total):
		from smart_power.sp_finance.posting import post

		entry = post(
			EVENT,
			doc,
			flt(doc.labour_total),
			posting_date=doc.work_date,
			cost_center=center(PROJECTS, doc.company),
			project=doc.project,
			credit_account=doc.paid_from or None,
			remark=_("Site labour of {0} on {1}").format(doc.station, doc.work_date),
		)
		doc.db_set("journal_entry", entry)


def _issue(doc) -> str:
	account = _account(doc.company, MATERIALS_ACCOUNT)
	if not account:
		frappe.throw(_("The company has no {0} account. Run the company setup.").format(MATERIALS_ACCOUNT))
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Issue",
			"purpose": "Material Issue",
			"company": doc.company,
			"posting_date": doc.work_date,
			"set_posting_time": 1,
			"project": doc.project,
			"remarks": _("Materials used on site: {0}").format(doc.name),
			"items": [
				{
					"item_code": r.item_code,
					"qty": r.qty,
					"s_warehouse": doc.site_warehouse,
					"expense_account": account,
					"cost_center": center(PROJECTS, doc.company),
					"project": doc.project,
				}
				for r in doc.materials
			],
		}
	)
	se.flags.ignore_permissions = True  # who may log the site is checked by the log's own rights
	se.insert()
	se.submit()
	return se.name


def before_cancel(doc) -> None:
	is_admin = frappe.session.user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles()))
	lock_days = int(frappe.db.get_single_value("Smart Power Settings", "field_entry_lock_days") or 0)
	if lock_days and not is_admin and getdate(doc.work_date) < getdate(add_days(today(), -lock_days)):
		frappe.throw(
			_("The log of {0} is locked ({1} days). Ask the admin.").format(
				frappe.format(doc.work_date, "Date"), lock_days
			),
			title=_("Locked"),
		)
	doc.ignore_linked_doctypes = ("Stock Entry", "Journal Entry")


def on_cancel(doc) -> None:
	"""The materials go back to the site; the labour entry is cancelled with the log (posting)."""
	if doc.stock_entry and frappe.db.get_value("Stock Entry", doc.stock_entry, "docstatus") == 1:
		se = frappe.get_doc("Stock Entry", doc.stock_entry)
		se.flags.ignore_permissions = True
		se.cancel()


# --- the station's actual cost ------------------------------------------------------------------


@frappe.whitelist()
def station_cost(station: str) -> dict:
	"""What posted to the station's project on expense accounts: {account: amount, "total": …}."""
	frappe.get_doc("SP Station", station).check_permission("read")
	project = frappe.db.get_value("SP Station", station, "project")
	rows = frappe.db.sql(
		"""select gle.account, sum(gle.debit - gle.credit) as amount
		from `tabGL Entry` gle join `tabAccount` acc on acc.name = gle.account
		where gle.project = %s and gle.is_cancelled = 0 and acc.root_type = 'Expense'
		group by gle.account""",
		project,
		as_dict=True,
	)
	out = {r.account: flt(r.amount) for r in rows}
	out["total"] = sum(out.values())
	return out


# --- setup ----------------------------------------------------------------------------------------


def seed_account_map(company: str) -> None:
	"""The Site Labour row of the Account Map, once: Dr Project Labour (the station's project,
	the center from the log) / Cr Daily Wages Payable (or the custody account on the log)."""
	from smart_power.constants import SETTINGS_DOCTYPE

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if any(r.event == EVENT for r in settings.account_map):
		return
	labour, payable = _account(company, LABOUR_ACCOUNT), _account(company, WAGES_PAYABLE)
	default_center = frappe.get_cached_value("Company", company, "cost_center")
	if not (labour and payable and default_center):
		return
	settings.append(
		"account_map",
		{
			"event": EVENT,
			"debit_account": labour,
			"debit_center_rule": "From document",
			"debit_cost_center": default_center,
			"credit_account": payable,
			"credit_center_rule": "Fixed",
			"credit_cost_center": default_center,
			"project_rule": "Debit side",
			"note": "Daily labour on a site; the credit is the custody account when the wages were paid from it.",
		},
	)
	settings.flags.ignore_permissions = True
	settings.save()


# --- photos usable for marketing ------------------------------------------------------------------

MARKETING_SOURCES = (LOG, "SP Station")
IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".mp4", ".mov")


@frappe.whitelist()
def photos(doctype: str, name: str) -> list[dict]:
	"""The photos and videos on a site log or station, with their marketing tag."""
	if doctype not in MARKETING_SOURCES:
		frappe.throw(_("Photos are tagged on a site log or a station."))
	frappe.get_doc(doctype, name).check_permission("read")
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": doctype, "attached_to_name": name, "is_folder": 0},
		fields=["name", "file_name", "file_url", "sp_usable_for_marketing"],
		order_by="creation asc",
	)
	return [f for f in files if (f.file_name or "").lower().endswith(IMAGE_TYPES)]


@frappe.whitelist(methods=["POST"])
def set_marketing(file: str, usable: int) -> None:
	"""Tag a site photo usable for marketing (or not); whoever may edit its log or station."""
	doctype, name = frappe.db.get_value("File", file, ["attached_to_doctype", "attached_to_name"]) or (
		None,
		None,
	)
	if doctype not in MARKETING_SOURCES:
		frappe.throw(_("Only photos of a site log or a station are tagged for marketing."))
	frappe.get_doc(doctype, name).check_permission("write" if doctype == "SP Station" else "read")
	if doctype == LOG and not frappe.has_permission(LOG, "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	frappe.db.set_value("File", file, "sp_usable_for_marketing", 1 if int(usable) else 0)
