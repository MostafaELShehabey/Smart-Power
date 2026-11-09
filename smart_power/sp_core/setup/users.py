"""Seed the Smart Power users from a CSV (SP-34).

Run once at cutover, after the emails or mobiles are known:
    bench --site <site> execute smart_power.sp_core.setup.users.seed_users --kwargs "{'path': '/path/users.csv'}"

The CSV has: full_name, email, mobile_no, role_profile, entry_mode (full or light).
Rows without an email are skipped. Existing users are left as they are.
"""

import csv
import os

import frappe

TEMPLATE = os.path.join(os.path.dirname(__file__), "users_seed_template.csv")


def seed_users(path: str = TEMPLATE) -> list[str]:
	created = []
	with open(path, encoding="utf-8") as f:
		for row in csv.DictReader(f):
			email = (row.get("email") or "").strip()
			if not email or frappe.db.exists("User", email):
				continue
			first, _, last = (row.get("full_name") or "").strip().partition(" ")
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": first or email,
					"last_name": last,
					"mobile_no": (row.get("mobile_no") or "").strip() or None,
					"language": "ar",
					"send_welcome_email": 0,
					"role_profile_name": (row.get("role_profile") or "").strip() or None,
					"sp_entry_mode": (row.get("entry_mode") or "full").strip().capitalize(),
				}
			)
			user.insert(ignore_permissions=True)
			created.append(email)
	return created
