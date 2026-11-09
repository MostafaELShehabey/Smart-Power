"""Sales setup values seeded once (SP-31). The admin can change them later in Selling Settings."""

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
