"""Quotation rules for Smart Power (SP-54).

A Smart Power quote belongs to an SP Case: its customer is the case's customer, and every
saved or submitted version marks an action on the case (for the inactivity rule, SP-71).
"""

import frappe
from frappe import _

from smart_power.sp_sales.case import touch

CASE = "SP Case"


def validate(doc, method=None) -> None:
	"""Quotation validate hook."""
	check_case(doc)


def on_update(doc, method=None) -> None:
	if doc.get("sp_case"):
		touch(doc.sp_case)


def check_case(doc) -> None:
	"""The quote is for the case's customer."""
	if not doc.get("sp_case"):
		return
	customer = frappe.db.get_value(CASE, doc.sp_case, "customer")
	if doc.quotation_to != "Customer" or doc.party_name != customer:
		frappe.throw(
			_("This quote is for {0}, but case {1} is for customer {2}.").format(
				frappe.bold(doc.party_name), frappe.bold(doc.sp_case), frappe.bold(customer)
			),
			title=_("Wrong customer"),
		)
