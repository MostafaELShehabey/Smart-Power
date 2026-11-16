"""SP-36: mobile login and the password policy; existing user mobiles in their local form."""

import frappe


def execute():
	from smart_power.sp_core.login import apply_login_settings
	from smart_power.sp_sales.customer import is_valid_mobile, normalize_mobile

	apply_login_settings()
	for user in frappe.get_all("User", filters={"mobile_no": ("is", "set")}, fields=["name", "mobile_no"]):
		mobile = normalize_mobile(user.mobile_no)
		if (
			is_valid_mobile(mobile)
			and mobile != user.mobile_no
			and not frappe.db.exists("User", {"mobile_no": mobile})
		):
			frappe.db.set_value("User", user.name, "mobile_no", mobile, update_modified=False)
