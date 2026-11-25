"""Company legal data for templates and reports (SP-25, X12).

Print formats, PDFs and the EgyptERA statement read the company's details from here, never
from text in the template. The cached document is refreshed when the admin saves X12.
"""

import frappe

COMPANY_SETTINGS = "SP Company Settings"
# the company's stacked logo, as on its letterhead (SP-185)
FALLBACK_LOGO = "/assets/smart_power/images/sp_logo_stacked.png"


def boot(bootinfo) -> None:
	"""The company the reports open on when the user has no default company of their own."""
	from smart_power.sp_stock.consignment import _default_company

	bootinfo.sp_company = _default_company()


def get_company_settings():
	"""The cached SP Company Settings (read-only use; no permission check, as templates need it)."""
	return frappe.get_cached_doc(COMPANY_SETTINGS)


def company_logo() -> str:
	"""The logo to print: the admin's upload, or the app logo until one is set."""
	return get_company_settings().logo or FALLBACK_LOGO


def company_addresses() -> list[dict]:
	"""Addresses in the admin's order, e.g. for a letterhead footer."""
	return [
		{"label": row.label, "address": row.address_ar, "phone": row.phone}
		for row in get_company_settings().addresses
	]
