"""A station's actual cost (SP-76, the Costs tab): what its project carries in the books.

    actual_cost(station) -> {"lines": [{"source", "amount"}], "direct", "indirect", "total"}

Every expense posted with the station's Project (its accounting dimension) counts, by source:

    purchases      Purchase Invoice / Receipt lines charged to the station
    consignment    the same, when the order converted consignment goods (SP-92)
    materials      Stock Entries: goods consumed on site, showroom goods at cost (SP-88..90)
    winch          the winch and car jobs' internal charge (SP-108)
    custody        custody and field spending (SP-118, SP-108)
    labour         the site's daily labour (SP-96)
    indirect       the station's share of the month's indirect pool (SP-124, "Indirect Split")
    other          any other expense on the project

The referrer's lump-sum commission is agreed on the contract (commission_amount) and counted
from there. When SP-177 posts it, it posts under the "Referrer Commission" event, which is
skipped here so it is not counted twice.
"""

import frappe
from frappe.utils import flt

STATION = "SP Station"
SOURCES = ("purchases", "consignment", "materials", "winch", "custody", "labour", "commission", "other")
INDIRECT = "indirect"
EVENT_SOURCE = {
	"Indirect Split": INDIRECT,
	"Winch Internal Charge": "winch",
	"Field Job": "winch",
	"Custody Expense": "custody",
	"Custody Settlement": "custody",
	"Field Expense": "custody",
	"Site Labour": "labour",
}
SKIPPED_EVENTS = ("Referrer Commission",)
PURCHASES = ("Purchase Invoice", "Purchase Receipt")


def _project_expenses(project: str) -> list[dict]:
	"""The project's expense balance per voucher, with the posting event of journal entries."""
	return frappe.db.sql(
		"""select gle.voucher_type, gle.voucher_no, je.sp_posting_event as event,
			sum(gle.debit - gle.credit) as amount
		from `tabGL Entry` gle
		join `tabAccount` acc on acc.name = gle.account
		left join `tabJournal Entry` je
			on gle.voucher_type = 'Journal Entry' and je.name = gle.voucher_no
		where gle.project = %(project)s and gle.is_cancelled = 0 and acc.root_type = 'Expense'
		group by gle.voucher_type, gle.voucher_no, je.sp_posting_event""",
		{"project": project},
		as_dict=True,
	)


def _is_consignment(voucher_type: str, voucher_no: str) -> bool:
	if voucher_type == "Purchase Receipt":
		order = frappe.db.get_value(voucher_type, voucher_no, "sp_purchase_order")
	else:
		order = frappe.db.get_value(
			"Purchase Invoice Item", {"parent": voucher_no, "purchase_order": ("is", "set")}, "purchase_order"
		)
	return bool(order and frappe.db.get_value("Purchase Order", order, "sp_is_consignment_conversion"))


def _source(row) -> str | None:
	if row.voucher_type == "Journal Entry":
		if row.event in SKIPPED_EVENTS:
			return None
		return EVENT_SOURCE.get(row.event, "other")
	if row.voucher_type in PURCHASES:
		return "consignment" if _is_consignment(row.voucher_type, row.voucher_no) else "purchases"
	if row.voucher_type == "Stock Entry":
		return "materials"
	return "other"


def actual_cost(station: str) -> dict:
	doc = frappe.db.get_value(STATION, station, ["project", "commission_amount"], as_dict=True)
	totals = dict.fromkeys((*SOURCES, INDIRECT), 0.0)
	if doc and doc.project:
		for row in _project_expenses(doc.project):
			source = _source(row)
			if source:
				totals[source] += flt(row.amount)
	totals["commission"] += flt(doc.commission_amount) if doc else 0.0
	direct = sum(totals[s] for s in SOURCES)
	return {
		"lines": [{"source": s, "amount": totals[s]} for s in (*SOURCES, INDIRECT) if totals[s]],
		"direct": direct,
		"indirect": totals[INDIRECT],
		"total": direct + totals[INDIRECT],
	}
