"""Shared helpers for Smart Power tests."""

import frappe
from frappe.utils import add_days, today

from smart_power.sp_core.setup.role_catalogue import role

# Selling Settings "Customer Naming By", stored as a global default.
CUSTOMER_NAMING_DEFAULT = "cust_master_name"
NAMING_BY_CUSTOMER_NAME = "Customer Name"


def load_erpnext_test_data() -> None:
	"""Create ERPNext's test company, customers and items (once per process).

	Import erpnext.tests.utils only through this:
	- its customers have no mobile, which the SP-31 Customer rule allows only while
	  frappe.flags.sp_loading_erpnext_test_data is set;
	- its records link customers by name ("_Test Customer"), so customers are named by
	  Customer Name while it loads, not CUS-##### (SP-31), then the site value is restored.
	"""
	naming = frappe.defaults.get_global_default(CUSTOMER_NAMING_DEFAULT)
	frappe.defaults.set_global_default(CUSTOMER_NAMING_DEFAULT, NAMING_BY_CUSTOMER_NAME)
	frappe.flags.sp_loading_erpnext_test_data = True
	try:
		import erpnext.tests.utils  # (bootstraps the records on import)
	finally:
		frappe.flags.sp_loading_erpnext_test_data = False
		frappe.defaults.set_global_default(CUSTOMER_NAMING_DEFAULT, naming)


def make_user(email: str, keys: tuple[str, ...] = (), extra_roles: tuple[str, ...] = ()) -> str:
	"""A test user holding the SP roles for the given catalogue keys (plus ERPNext base roles)."""
	from smart_power.sp_core.setup.role_catalogue import BY_KEY

	roles = {role(k) for k in keys} | set(extra_roles)
	for k in keys:
		roles.update(BY_KEY[k].erpnext_roles)
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		user.set("roles", [])
	else:
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		)
	for r in sorted(roles):
		user.append("roles", {"role": r})
	user.flags.ignore_permissions = True
	user.save() if not user.is_new() else user.insert()
	return email


def set_setting(**values) -> None:
	doc = frappe.get_single("Smart Power Settings")
	doc.update(values)
	doc.flags.ignore_permissions = True
	doc.save()
	frappe.clear_document_cache("Smart Power Settings", "Smart Power Settings")


def set_rule(key: str, level: str, warn_needs_reason: int | None = None, limits: str | None = None) -> None:
	doc = frappe.get_doc("SP Rule Setting", key)
	doc.level = level
	if warn_needs_reason is not None:
		doc.warn_needs_reason = warn_needs_reason
	if limits is not None:
		doc.limits = limits
	doc.save(ignore_permissions=True)


def make_test_case(customer: str = "_Test Customer") -> str:
	"""An SP Case for ERPNext's test customer: every quote belongs to a case (SP-54)."""
	return (
		frappe.get_doc(
			{
				"doctype": "SP Case",
				"customer": customer,
				"channel": "Call",
				"follow_up_owner": "Administrator",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_quotation(
	discount_pct: float = 0,
	valid_days: int = 1,
	rate: float = 1000,
	save: bool = True,
	case: str | None = None,
):
	"""A quotation on ERPNext's test records (bootstrapped by erpnext.tests.utils), on a case."""
	q = frappe.get_doc(
		{
			"doctype": "Quotation",
			"sp_case": case or make_test_case(),
			"quotation_to": "Customer",
			"party_name": "_Test Customer",
			"company": "_Test Company",
			"currency": frappe.get_cached_value("Company", "_Test Company", "default_currency"),
			"conversion_rate": 1,
			"transaction_date": today(),
			"valid_till": add_days(today(), valid_days),
			"selling_price_list": "Standard Selling",
			"apply_discount_on": "Grand Total",
			"additional_discount_percentage": discount_pct,
			"items": [{"item_code": "_Test Item", "qty": 1, "rate": rate}],
		}
	)
	if save:
		q.insert()
	return q


def make_customer(mobile: str, name: str = "عميل تجربة", **kw) -> str:
	"""A customer with an Egyptian mobile (SP-31); returns its name. Reuses one with that mobile."""
	existing = frappe.db.get_value("Customer", {"sp_mobile": mobile})
	if existing:
		return existing
	return (
		frappe.get_doc({"doctype": "Customer", "customer_name": name, "sp_mobile": mobile, **kw})
		.insert()
		.name
	)


SUPPLY_DAYS, INSTALL_DAYS = 30, 15  # sp-allow-number: test contract periods


def sign_contract(so):
	"""Sign (submit) a contract Sales Order with the periods it prints (SP-75)."""
	if isinstance(so, str):
		so = frappe.get_doc("Sales Order", so)
	so.sp_supply_days = so.get("sp_supply_days") or SUPPLY_DAYS
	so.sp_install_days = so.get("sp_install_days") or INSTALL_DAYS
	so.submit()
	return so
