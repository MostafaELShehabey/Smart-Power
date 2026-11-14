"""Sales setup values seeded once (SP-31, SP-55). The admin can change them later in Selling Settings."""

import frappe

NAMING_BY_SERIES = "Naming Series"


def apply_customer_naming() -> None:
	"""Customers are numbered CUS-00001, CUS-00002 … (series options ship as property setters)."""
	settings = frappe.get_single("Selling Settings")
	if settings.cust_master_name == NAMING_BY_SERIES:
		return
	settings.cust_master_name = NAMING_BY_SERIES
	settings.flags.ignore_mandatory = True
	settings.flags.ignore_permissions = True
	settings.save()


def allow_repeated_items() -> None:
	"""The same item may appear on more than one line of a quote, order or invoice (SP-55): a
	calculation template can use one item on two lines (e.g. the same cable twice), and a quote
	creator can add a row by hand for an item the template also prices. Set once; the admin can
	turn it off again in Selling Settings."""
	settings = frappe.get_single("Selling Settings")
	if settings.allow_multiple_items:
		return
	settings.allow_multiple_items = 1
	settings.flags.ignore_mandatory = True
	settings.flags.ignore_permissions = True
	settings.save()
