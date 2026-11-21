"""A16 Indirect cost split (SP-124; journey J11; ERD 7.4 IndirectSplit, data note 8-11-2026).

The month's pool is everything posted on the Indirect Pool center in the month (salaries, wages,
office rent, general costs, project petty cash with no station, SP-123). The admin shares it,
with no fixed ratio, between the stations technically or financially closed that month, the
showroom and, if he wants, the winch and the Jumbo: each share an amount or a % of the pool.
The shares must add up to the pool (to the pound); submitting posts one Journal Entry (event
"Indirect Split"):

    Cr  the Account Map's credit account (Indirect Cost Pool)  on the Indirect Pool center
    Dr  its debit account (Indirect Cost Allocated)            on each target's center; a
                                                               station's on Projects with its
                                                               project (no Station dimension)

so the pool center nets 0 and each station's Costs tab shows its share as "indirect" (SP-76).
One split per company and month; cancelling it cancels its entry.

    closed_stations(company, month)   the stations closed in the month
    suggest(company, month)           the pool and a line per closed station and the showroom
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate

from smart_power.sp_finance.centers import INDIRECT, JUMBO, SHOWROOM, WINCH, center, station_center

SPLIT, STATION = "SP Indirect Split", "SP Station"
EVENT = "Indirect Split"
ALLOCATED_ACCOUNT, POOL_ACCOUNT = "Indirect Cost Allocated", "Indirect Cost Pool"
TARGET_KEYS = {"Showroom": SHOWROOM, "Winch": WINCH, "Jumbo": JUMBO}
TOLERANCE = 1  # sp-allow-number: the story's ±1 when the shares are checked against the pool
MONEY_DIGITS = 2  # sp-allow-number: currency precision
ADMIN_ROLES = ("SP Admin", "System Manager")


def _check_admin() -> None:
	if frappe.session.user != "Administrator" and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin splits the indirect costs."), frappe.PermissionError)


def _month(day) -> tuple:
	day = getdate(day)
	return get_first_day(day), get_last_day(day)


def pool_amount(company: str, month) -> float:
	"""What the Indirect Pool center carries in the month, before any split."""
	start, end = _month(month)
	pool = center(INDIRECT, company)
	if not pool:
		return 0.0
	(amount,) = frappe.db.sql(
		"""select coalesce(sum(gle.debit - gle.credit), 0)
		from `tabGL Entry` gle
		join `tabAccount` acc on acc.name = gle.account
		left join `tabJournal Entry` je
			on gle.voucher_type = 'Journal Entry' and je.name = gle.voucher_no
		where gle.company = %(company)s and gle.cost_center = %(pool)s and gle.is_cancelled = 0
			and acc.root_type = 'Expense' and gle.posting_date between %(start)s and %(end)s
			and coalesce(je.sp_posting_event, '') != %(event)s""",
		{"company": company, "pool": pool, "start": start, "end": end, "event": EVENT},
	)[0]
	return flt(amount)


def closed_stations(company: str, month) -> list[str]:
	"""Stations technically or financially closed in the month (they take the month's pool)."""
	start, end = _month(month)
	rows = frappe.get_all(
		STATION,
		{"company": company, "status": ("in", ("Technically closed", "Financially closed"))},
		["name", "tech_closed_on", "fin_closed_on"],
		order_by="name asc",
	)
	return [
		r.name
		for r in rows
		if any(d and start <= getdate(d) <= end for d in (r.tech_closed_on, r.fin_closed_on))
	]


@frappe.whitelist()
def suggest(company: str, month: str) -> dict:
	"""For the form: the pool, and one line per closed station plus the showroom (no amounts)."""
	_check_admin()
	lines = [{"target_type": "Station", "station": s} for s in closed_stations(company, month)]
	lines.append({"target_type": "Showroom"})
	return {"pool_amount": pool_amount(company, month), "lines": lines}


def validate(doc) -> None:
	_check_admin()
	start, _end = _month(doc.month)
	doc.month = start
	other = frappe.db.get_value(
		SPLIT,
		{"company": doc.company, "month": start, "docstatus": 1, "name": ("!=", doc.name)},
	)
	if other:
		frappe.throw(_("{0} already splits this month.").format(frappe.bold(other)))
	if doc.docstatus == 0 or not doc.pool_amount:
		doc.pool_amount = pool_amount(doc.company, start)
	for row in doc.lines:
		if row.target_type == "Station":
			if not row.station:
				frappe.throw(_("Row {0}: choose the station.").format(row.idx), frappe.MandatoryError)
			row.project = frappe.db.get_value(STATION, row.station, "project")
			row.cost_center = station_center(doc.company)
		else:
			row.station = row.project = None
			row.cost_center = center(TARGET_KEYS[row.target_type], doc.company)
		if not flt(row.amount) and flt(row.pct):
			row.amount = flt(doc.pool_amount * flt(row.pct) / 100, MONEY_DIGITS)
		if flt(row.amount) < 0:
			frappe.throw(_("Row {0}: a share cannot be negative.").format(row.idx))
	doc.total_amount = sum(flt(r.amount) for r in doc.lines)
	doc.difference = flt(doc.pool_amount - doc.total_amount, MONEY_DIGITS)


def _accounts(company: str) -> tuple[str, str]:
	from smart_power.sp_core.services.settings import account_map

	row = account_map(EVENT)

	def of(name, mapped):
		if mapped and frappe.db.get_value("Account", mapped, "company") == company:
			return mapped
		return frappe.db.get_value("Account", {"company": company, "account_name": name, "is_group": 0})

	debit = of(ALLOCATED_ACCOUNT, row.debit_account if row else None)
	credit = of(POOL_ACCOUNT, row.credit_account if row else None)
	if not (debit and credit):
		frappe.throw(
			_("Map the Indirect Split event in Smart Power Settings > Account Map."), title=_("Account Map")
		)
	return debit, credit


def on_submit(doc) -> None:
	"""The shares must add up to the pool; one entry moves the pool into its targets."""
	from smart_power.sp_finance.custody import _journal

	if flt(doc.pool_amount) <= 0:
		frappe.throw(_("The Indirect Pool has nothing to split this month."))
	if abs(flt(doc.difference)) > TOLERANCE:
		frappe.throw(
			_("The shares add up to {0}, not the pool's {1}.").format(
				frappe.format(doc.total_amount, "Currency"), frappe.format(doc.pool_amount, "Currency")
			),
			title=_("Indirect split"),
		)
	debit, credit = _accounts(doc.company)
	accounts = [
		{
			"account": debit,
			"debit_in_account_currency": flt(r.amount),
			"cost_center": r.cost_center,
			"project": r.project,
			"user_remark": r.station or _(r.target_type),
		}
		for r in doc.lines
		if flt(r.amount)
	]
	accounts.append(
		{
			"account": credit,
			"credit_in_account_currency": flt(doc.total_amount),
			"cost_center": center(INDIRECT, doc.company),
		}
	)
	_start, end = _month(doc.month)
	frappe.flags.sp_system_posting = True  # the posting is the system's (SP-26)
	try:
		entry = _journal(doc, end, accounts, EVENT, _("Indirect split of {0}").format(doc.month))
	finally:
		frappe.flags.sp_system_posting = False
	doc.db_set("journal_entry", entry)


def seed_account_map(company: str) -> None:
	"""The Indirect Split row of the Account Map, once. The admin can change it."""
	from smart_power.constants import SETTINGS_DOCTYPE

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if any(r.event == EVENT for r in settings.account_map):
		return
	debit = frappe.db.get_value(
		"Account", {"company": company, "account_name": ALLOCATED_ACCOUNT, "is_group": 0}
	)
	credit = frappe.db.get_value("Account", {"company": company, "account_name": POOL_ACCOUNT, "is_group": 0})
	cc = frappe.get_cached_value("Company", company, "cost_center")
	if not (debit and credit and cc):
		return
	settings.append(
		"account_map",
		{
			"event": EVENT,
			"debit_account": debit,
			"debit_center_rule": "From document",
			"debit_cost_center": cc,
			"credit_account": credit,
			"credit_center_rule": "From document",
			"credit_cost_center": cc,
			"project_rule": "Debit side",
			"note": "The month's indirect pool moved into the stations closed that month and the showroom.",
		},
	)
	settings.flags.ignore_permissions = True
	settings.save()
