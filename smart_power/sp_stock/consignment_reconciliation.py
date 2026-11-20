"""Consignment reconciliation (SP-93, I7): our container figures against the supplier's monthly
statement. The supplier's goods stay outside the stock ledger (SP-91), so this compares
quantities only and never posts.

    our figures, per container, as of the month's last day:
        received      the container's panels, if it arrived by then
        withdrawn     withdrawn for Smart Power (SP-92), handed over to the supplier's customers,
        handed over   returned to the supplier: the submitted movements dated by then
        remaining     received - withdrawn - handed over - returned
    the supplier's figures are typed from the statement; the difference is theirs minus ours on
    what remains (the story's example: our 1,224, theirs 1,200, so -24)

    load(name)                 our figures for every container the supplier had with us
    finish(name)               Matched, or With differences (each differing line needs a note):
                               the admin is told and it is listed in the review centre (RV2)
    create_monthly()           daily: on the 1st, a sheet per supplier for the month just closed,
                               and a task for the main store keeper (owner, 2026-11-20)

The supplier's statement file is required to finish (owner, 2026-11-20).
"""

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	add_months,
	cint,
	get_first_day,
	get_last_day,
	getdate,
	now_datetime,
	nowdate,
)

from smart_power.sp_core.inbox import close_tasks, create_task
from smart_power.sp_stock.consignment import CONTAINER, HAND_OVER, MOVEMENT, RETURN, WITHDRAW

RECONCILIATION = "SP Consignment Reconciliation"
DRAFT, MATCHED, WITH_DIFFERENCES = "Draft", "Matched", "With differences"
LINE_MATCHED, LINE_DIFFERENCE = "Matched", "Difference"
TASK = "Consignment Reconciliation"
EVENT_DIFFERENCE = "consignment_reco_difference"
REVIEW_CATEGORY = "Count Difference"
KEEPER = "SP Main Store Keeper"
ADMIN = "SP Admin"
DECIDERS = (KEEPER, ADMIN, "System Manager")
# each figure of ours and the statement's that must agree
PAIRS = (
	("our_received", "supplier_received"),
	("our_withdrawn", "supplier_withdrawn"),
	("our_handed_over", "supplier_handed_over"),
	("our_remaining", "supplier_remaining"),
)


def _can_reconcile(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(DECIDERS) & set(frappe.get_roles(user)))


def _check():
	if not _can_reconcile():
		frappe.throw(_("Only the main store keeper reconciles consignment."), frappe.PermissionError)


def validate_reconciliation(doc) -> None:
	if not frappe.db.get_value("Supplier", doc.supplier, "sp_is_consignment_owner"):
		frappe.throw(_("{0} does not keep goods with us on consignment.").format(frappe.bold(doc.supplier)))
	doc.period = get_first_day(doc.period)
	doc.period_end = get_last_day(doc.period)
	if doc.is_new() and frappe.db.exists(
		RECONCILIATION, {"supplier": doc.supplier, "company": doc.company, "period": doc.period}
	):
		frappe.throw(_("{0} is already reconciled for this month.").format(doc.supplier))
	if doc.status != DRAFT and not doc.flags.sp_finishing:
		previous = doc.get_doc_before_save()
		if previous and _figures(previous) != _figures(doc):
			frappe.throw(
				_("Reconciliation {0} is finished: its figures can no longer change.").format(doc.name)
			)
	for line in doc.lines:
		_compare(line)
	doc.differences = sum(1 for line in doc.lines if line.line_status == LINE_DIFFERENCE)


def _figures(doc) -> list:
	return [(l.container, *(cint(l.get(f)) for pair in PAIRS for f in pair)) for l in doc.lines]


def _compare(line) -> None:
	line.our_remaining = (
		cint(line.our_received)
		- cint(line.our_withdrawn)
		- cint(line.our_handed_over)
		- cint(line.our_returned)
	)
	line.diff = cint(line.supplier_remaining) - cint(line.our_remaining)
	agrees = all(cint(line.get(ours)) == cint(line.get(theirs)) for ours, theirs in PAIRS)
	line.line_status = LINE_MATCHED if agrees else LINE_DIFFERENCE


def our_figures(container: str, as_of) -> dict:
	"""What our records hold for a container on a day."""
	as_of = getdate(as_of)
	received_on, received = frappe.db.get_value(CONTAINER, container, ["received_on", "received_qty"])
	rows = frappe.get_all(
		MOVEMENT,
		{
			"container": container,
			"docstatus": 1,
			"movement_type": ("in", (WITHDRAW, HAND_OVER, RETURN)),
			"movement_date": ("<=", as_of),
		},
		["movement_type", "qty"],
	)

	def total(kind):
		return sum(cint(r.qty) for r in rows if r.movement_type == kind)

	return {
		"our_received": cint(received) if not received_on or getdate(received_on) <= as_of else 0,
		"our_withdrawn": total(WITHDRAW),
		"our_handed_over": total(HAND_OVER),
		"our_returned": total(RETURN),
	}


def _containers(supplier: str, company: str, start, end) -> list[str]:
	"""The supplier's containers that held panels with us during the month: arrived by its end,
	and not emptied before it began."""
	names = []
	for c in frappe.get_all(
		CONTAINER,
		{"supplier": supplier, "company": company},
		["name", "received_on"],
		order_by="received_on asc, name asc",
	):
		if c.received_on and getdate(c.received_on) > getdate(end):
			continue
		before = our_figures(c.name, add_days(start, -1))
		left_before = (
			before["our_received"]
			- before["our_withdrawn"]
			- before["our_handed_over"]
			- before["our_returned"]
		)
		moved = frappe.db.exists(
			MOVEMENT, {"container": c.name, "docstatus": 1, "movement_date": ("between", (start, end))}
		)
		if left_before > 0 or moved or (c.received_on and getdate(c.received_on) >= getdate(start)):
			names.append(c.name)
	return names


def _load(doc) -> None:
	"""Our figures for each container; the supplier's figures already typed are kept."""
	doc.period = get_first_day(doc.period)
	doc.period_end = get_last_day(doc.period)
	typed = {line.container: line for line in doc.lines}
	doc.set("lines", [])
	for container in _containers(doc.supplier, doc.company, doc.period, doc.period_end):
		row = {"container": container, **our_figures(container, doc.period_end)}
		old = typed.get(container)
		if old:
			row.update({theirs: old.get(theirs) for _ours, theirs in PAIRS})
			row["note"] = old.note
		doc.append("lines", row)


@frappe.whitelist(methods=["POST"])
def load(name: str) -> dict:
	_check()
	doc = frappe.get_doc(RECONCILIATION, name)
	if doc.status != DRAFT:
		frappe.throw(_("Reconciliation {0} is finished.").format(name))
	_load(doc)
	doc.flags.ignore_permissions = True  # checked above
	doc.save()
	return {"lines": len(doc.lines)}


@frappe.whitelist(methods=["POST"])
def finish(name: str) -> dict:
	"""Matched when every container agrees; else With differences, which tells the admin."""
	_check()
	doc = frappe.get_doc(RECONCILIATION, name)
	if doc.status != DRAFT:
		frappe.throw(_("Reconciliation {0} is finished.").format(name))
	if not doc.statement_file:
		frappe.throw(_("Attach the supplier's statement before finishing."))
	if not doc.lines:
		frappe.throw(_("Load the containers first."))
	for line in doc.lines:
		_compare(line)
	unexplained = [
		line.container_no or line.container
		for line in doc.lines
		if line.line_status == LINE_DIFFERENCE and not (line.note or "").strip()
	]
	if unexplained:
		frappe.throw(_("Write a note on each container that differs: {0}").format(", ".join(unexplained)))
	doc.status = WITH_DIFFERENCES if any(l.line_status == LINE_DIFFERENCE for l in doc.lines) else MATCHED
	doc.reconciled_by = frappe.session.user
	doc.reconciled_on = now_datetime()
	doc.flags.ignore_permissions = True
	doc.flags.sp_finishing = True
	doc.save()
	close_tasks(RECONCILIATION, doc.name, TASK)
	if doc.status == WITH_DIFFERENCES:
		_tell_admin(doc)
	return {"status": doc.status, "differences": doc.differences}


def _tell_admin(doc) -> None:
	from smart_power.notify import send
	from smart_power.sp_core.review_centre import raise_item
	from smart_power.sp_sales.quote_request import _users_with

	lines = [l for l in doc.lines if l.line_status == LINE_DIFFERENCE]
	summary = _("Consignment {0}, {1}: {2} containers differ from the statement ({3})").format(
		doc.supplier,
		frappe.utils.formatdate(doc.period, "MM-yyyy"),
		len(lines),
		", ".join(f"{l.container_no or l.container} {l.diff:+d}" for l in lines),
	)
	raise_item(REVIEW_CATEGORY, doc, summary)
	send(EVENT_DIFFERENCE, _users_with(ADMIN), RECONCILIATION, doc.name, summary, from_user="Administrator")


# ---------------------------------------------------------------- the monthly sheet


def _consignment_suppliers() -> list[tuple[str, str]]:
	return frappe.db.sql(
		"""select distinct c.supplier, c.company from `tabSP Consignment Container` c
		join `tabSupplier` s on s.name = c.supplier and s.sp_is_consignment_owner = 1
		where ifnull(c.company, '') != ''"""
	)


def create_monthly(day=None) -> list[str]:
	"""Daily: from the 1st, each consignment supplier gets one sheet for the month just closed
	(made later in the month if a day was missed), and the main store keepers a task."""
	from smart_power.sp_sales.quote_request import _users_with

	month = get_first_day(add_months(getdate(day or nowdate()), -1))
	made = []
	for supplier, company in _consignment_suppliers():
		if frappe.db.exists(RECONCILIATION, {"supplier": supplier, "company": company, "period": month}):
			continue
		doc = frappe.get_doc(
			{"doctype": RECONCILIATION, "supplier": supplier, "company": company, "period": month}
		)
		_load(doc)
		if not doc.lines:
			continue
		doc.flags.ignore_permissions = True
		doc.insert()
		create_task(
			TASK,
			RECONCILIATION,
			doc.name,
			_users_with(KEEPER),
			_("Reconcile {0}'s consignment for {1} with its statement").format(
				supplier, frappe.utils.formatdate(month, "MM-yyyy")
			),
		)
		made.append(doc.name)
	return made


def due_count(user: str | None = None) -> int:
	"""Sheets still waiting for the statement: the store home card (SP-93)."""
	return frappe.db.count(RECONCILIATION, {"status": DRAFT}) if _can_reconcile(user) else 0
