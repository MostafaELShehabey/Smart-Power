"""Arabic and Egyptian defaults for the site (SP-22)."""

import frappe

from smart_power.sp_core.setup.seed import defaults


def apply_locale(*args, **kwargs) -> None:
	"""Set System Settings, the default currency and the fiscal year. Safe to run again.

	Also hooked to setup_wizard_complete, because the ERPNext setup wizard rewrites some of them.
	"""
	values = {k: v for k, v in defaults()["system_settings"].items() if not k.startswith("_")}
	if frappe.db.exists("Currency", values["currency"]):
		frappe.db.set_value("Currency", values["currency"], "enabled", 1)

	ss = frappe.get_single("System Settings")
	ss.update(values)
	ss.flags.ignore_mandatory = True
	ss.flags.ignore_permissions = True
	ss.save()

	frappe.db.set_default("currency", values["currency"])
	frappe.db.set_default("country", values["country"])
	frappe.db.set_default("date_format", values["date_format"])
	frappe.db.set_default("time_format", values["time_format"])
	if frappe.db.exists("DocType", "Global Defaults"):
		frappe.db.set_single_value("Global Defaults", "default_currency", values["currency"])
		frappe.db.set_single_value("Global Defaults", "country", values["country"])

	for fy in defaults().get("fiscal_years", []):
		if frappe.db.exists("DocType", "Fiscal Year") and not frappe.db.exists("Fiscal Year", fy["year"]):
			frappe.get_doc(
				{
					"doctype": "Fiscal Year",
					"year": fy["year"],
					"year_start_date": fy["year_start_date"],
					"year_end_date": fy["year_end_date"],
				}
			).insert(ignore_permissions=True)


def apply_branding() -> None:
	"""Logo and app name on the desk, login page and website."""
	logo = "/assets/smart_power/images/sp_logo.png"
	if frappe.db.exists("DocType", "Navbar Settings"):
		frappe.db.set_single_value("Navbar Settings", "app_logo", logo)
	ws = frappe.get_single("Website Settings")
	ws.app_name = "Smart Power"
	ws.app_logo = logo
	ws.favicon = "/assets/smart_power/images/sp_favicon.png"
	ws.flags.ignore_permissions = True
	ws.save()
