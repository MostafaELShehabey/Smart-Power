"""Login (SP-36, G1): mobile or email, a lock after failed tries, reset through the admin, and a
password change at the first login.

- A user signs in with their email or their mobile (01xxxxxxxxx, also typed as +20 or 0020).
  The mobile is stored in that local form, so it matches; Frappe keeps it unique.
"""

import frappe

from smart_power.sp_core.setup.seed import defaults
from smart_power.sp_sales.customer import is_valid_mobile, normalize_mobile


def apply_login_settings() -> None:
	"""Mobile login and the password policy in System Settings."""
	frappe.db.set_single_value("System Settings", defaults()["login"]["system_settings"])


def validate_user(doc, method=None) -> None:
	"""User validate: an Egyptian mobile in its local form (others are left as typed)."""
	mobile = login_name(doc.get("mobile_no"))
	if mobile:
		doc.mobile_no = mobile


def login_name(value: str | None) -> str | None:
	"""What the user typed to sign in: a mobile in any form becomes its local form."""
	if not value or "@" in value:
		return value
	mobile = normalize_mobile(value)
	return mobile if is_valid_mobile(mobile) else value


def before_login(login_manager=None) -> None:
	"""before_login: a mobile typed as +20 or with spaces still finds the user."""
	usr = frappe.form_dict.get("usr")
	if usr:
		frappe.form_dict.usr = login_name(usr)
