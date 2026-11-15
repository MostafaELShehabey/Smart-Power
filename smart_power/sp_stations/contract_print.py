"""The contract PDF (SP-74): what "SP Contract" prints for a Sales Order.

    contract_print(doc) -> {header, lines, totals, schedule, cheques}

The clauses (supply and installation periods, warranty, ownership until full payment) are the
admin's Contract template text (SP-134), never code. The components carry the warranty years of
the approved quote's lines. The referrer's lump sum and every cost stay off the paper.
"""

import frappe
from frappe.utils import flt

from smart_power.sp_core.printing import ar_date, ar_words
from smart_power.sp_quotes.quote_print import print_lines


def contract_print(doc) -> frappe._dict:
	total = flt(doc.get("rounded_total") or doc.get("grand_total"))
	financing = doc.get("sp_financing_type")
	return frappe._dict(
		header=frappe._dict(
			contract_no=doc.get("name"),
			station=doc.get("sp_station") or "",
			date=ar_date(doc.get("transaction_date")),
			customer=doc.get("customer_name") or doc.get("customer"),
			financing=frappe.db.get_value("SP List Value", financing, "value_ar") if financing else "",
			bank_branch=doc.get("sp_bank_branch") or "",
			site=frappe.db.get_value("SP Station", doc.sp_station, "location_text")
			if doc.get("sp_station")
			else "",
		),
		lines=print_lines(doc.get("items") or []),
		totals=frappe._dict(
			subtotal=flt(doc.get("total")),
			discount=flt(doc.get("discount_amount")),
			total=total,
			words=ar_words(total),
			currency=doc.get("currency"),
		),
		schedule=[
			{
				"due_date": ar_date(r.due_date),
				"amount": flt(r.payment_amount),
				"description": r.get("description") or "",
			}
			for r in doc.get("payment_schedule") or []
		],
		cheques=[
			{
				"cheque_no": r.cheque_no,
				"bank": r.bank or "",
				"due_date": ar_date(r.due_date),
				"amount": flt(r.amount),
			}
			for r in doc.get("sp_cheques") or []
		],
	)
