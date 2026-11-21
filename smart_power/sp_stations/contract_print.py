"""The contract PDF (SP-74): what "SP Contract" prints for a Sales Order.

    contract_print(doc) -> {header, parties, lines, totals, schedule, cheques, stamp}

The clauses (supply and installation periods, warranty, ownership until full payment) are the
admin's Contract template text (SP-134), never code. The components carry the warranty years of
the approved quote's lines. The referrer's lump sum and every cost stay off the paper.

The parties (SP-75): the company's legal data from its settings (X12), and the customer's name,
national ID, address and mobile. The company's stamp sits by its signature.
"""

import frappe
from frappe.utils import flt, strip_html

from smart_power.sp_core.printing import ar_date, ar_words
from smart_power.sp_quotes.quote_print import print_lines


def _company() -> frappe._dict:
	from smart_power.sp_core.services.company import company_addresses, get_company_settings

	settings = get_company_settings()
	addresses = company_addresses()
	return frappe._dict(
		name=settings.legal_name_ar or settings.company or "",
		represented_by=settings.owner_name or "",
		commercial_register=settings.commercial_register or "",
		tax_card=settings.tax_card or "",
		address=addresses[0]["address"] if addresses else "",
	)


def _customer(doc) -> frappe._dict:
	customer = (
		frappe.db.get_value(
			"Customer", doc.get("customer"), ["sp_national_id", "sp_mobile", "customer_name"], as_dict=True
		)
		if doc.get("customer")
		else None
	) or frappe._dict()
	address = strip_html((doc.get("address_display") or "").replace("<br>", "، ")).strip(" ،\n")
	return frappe._dict(
		name=doc.get("customer_name") or customer.customer_name or doc.get("customer") or "",
		national_id=customer.sp_national_id or "",
		address=address,
		mobile=customer.sp_mobile or doc.get("contact_mobile") or "",
	)


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
		parties=frappe._dict(company=_company(), customer=_customer(doc)),
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
		stamp=_stamp(),
	)


def _stamp() -> str:
	from smart_power.sp_core.printing import embed_image
	from smart_power.sp_core.services.company import get_company_settings

	stamp = get_company_settings().stamp_image
	return embed_image(stamp) if stamp else ""
