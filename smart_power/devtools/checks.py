"""Post-install smoke check, run by CI on a fresh site (SP-19 acceptance criteria).

bench --site test_site execute smart_power.devtools.checks.post_install
"""

import frappe

from smart_power.sp_core.setup.role_catalogue import PROFILES, ROLES


def post_install() -> None:
	problems = []
	ss = frappe.get_single("System Settings")
	if (ss.language, ss.date_format, ss.time_zone) != ("ar", "dd-mm-yyyy", "Africa/Cairo"):
		problems.append(f"locale not applied: {ss.language} {ss.date_format} {ss.time_zone}")
	missing_roles = [r.role_name for r in ROLES if not frappe.db.exists("Role", r.role_name)]
	if missing_roles:
		problems.append(f"roles missing: {missing_roles}")
	missing_profiles = [p.name for p in PROFILES if not frappe.db.exists("Role Profile", p.name)]
	if missing_profiles:
		problems.append(f"role profiles missing: {missing_profiles}")
	if not frappe.db.exists("Custom Field", "User-sp_entry_mode"):
		problems.append("User custom fields missing")
	if not frappe.db.get_single_value("Smart Power Settings", "validity_days"):
		problems.append("Smart Power Settings not seeded")
	if not frappe.db.count("SP Rule Setting"):
		problems.append("rule settings not synced")
	if not frappe.db.exists("Module Def", "Smart Power Admin"):
		problems.append("admin module missing")
	if problems:
		raise SystemExit("post-install check failed:\n- " + "\n- ".join(problems))
	print("post-install check passed")
