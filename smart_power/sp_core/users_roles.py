"""X1 Users and roles (SP-130): the admin manages the team's logins in one screen.

    overview()                       users with their role keys, last login, device, entry mode,
                                     home, lock and money accounts; the role catalogue
    add_user(values)                 a new hire with role keys, entry mode and home; returns a
                                     one-time temporary password, changed at the first sign-in
                                     (owner, 2026-11-22: no welcome email)
    set_enabled / set_roles / set_home / set_entry_mode / create_accounts
    reset_password(user)             a new temporary password; the account is unlocked
    unlock(user)                     after the failed sign-ins (SP-36)
    revoke_device(device)            the phone is off and the user's API secret is replaced, so
                                     its next sync gets 401 (owner, 2026-11-22; E16's app asks for
                                     login on 401)

Only SP roles are given or taken here, each with the ERPNext roles it stands on (role catalogue).
Every change is audited (X13).
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from smart_power.sp_core.services.audit import audit
from smart_power.sp_core.setup.role_catalogue import BY_KEY, ROLES

USER, DEVICE = "User", "SP Mobile Device"
ADMIN_ROLES = ("SP Admin", "System Manager")
ENTRY_MODES = ("Full", "Light")
SECRET_LENGTH = 15  # sp-allow-number: the length Frappe's own key generation uses
# the G2 home variants (dashboards.cards.VARIANTS), as the admin reads them
HOME_LABELS = {
	"intake": "Intake",
	"marketing": "Marketing",
	"tech_office": "Technical Office",
	"projects": "Projects",
	"installations": "Installations",
	"store": "Stores",
	"showroom": "Showroom",
	"finance": "Finance",
	"compliance": "Compliance",
}


def _check_admin() -> None:
	if frappe.session.user != "Administrator" and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin manages users and roles."), frappe.PermissionError)


def _team_user(user: str):
	if user in frappe.STANDARD_USERS or not frappe.db.exists(USER, user):
		frappe.throw(_("{0} is not a team member.").format(user))
	doc = frappe.get_doc(USER, user)
	if doc.user_type == "Website User":
		frappe.throw(_("{0} is not a team member.").format(user))
	return doc


def keys_of(roles) -> list[str]:
	held = set(roles)
	return [r.key for r in ROLES if r.role_name in held]


def _roles_for(keys) -> set[str]:
	roles = set()
	for key in keys:
		if key not in BY_KEY:
			frappe.throw(_("Unknown role key {0}.").format(frappe.bold(key)))
		roles.add(BY_KEY[key].role_name)
		roles.update(BY_KEY[key].erpnext_roles)
	return roles


def _given_by_catalogue() -> set[str]:
	"""Every role X1 may give or take: the SP roles and the ERPNext roles they stand on."""
	return _roles_for(BY_KEY)


# --- the list ----------------------------------------------------------------------------------


@frappe.whitelist()
def overview() -> dict:
	from smart_power.dashboards.cards import VARIANTS

	_check_admin()
	users = frappe.get_all(
		USER,
		filters={"user_type": "System User", "name": ("not in", frappe.STANDARD_USERS)},
		fields=[
			"name",
			"full_name",
			"enabled",
			"last_login",
			"mobile_no",
			"sp_entry_mode",
			"sp_home_page",
			"sp_login_locked",
		],
		order_by="full_name asc",
	)
	roles = {}
	for row in frappe.get_all(
		"Has Role",
		{"parenttype": USER, "parent": ("in", [u.name for u in users] or [""])},
		["parent", "role"],
	):
		roles.setdefault(row.parent, []).append(row.role)
	devices = {}
	for d in frappe.get_all(
		DEVICE,
		{"active": 1},
		["name", "user", "device_id", "device_name", "last_sync"],
		order_by="last_sync desc",
	):
		devices.setdefault(d.user, d)
	held = {}
	for a in frappe.get_all(
		"Account",
		{
			"sp_holder": ("in", [u.name for u in users] or [""]),
			"sp_account_kind": ("in", ("Transit", "Custody")),
		},
		["name", "sp_holder", "sp_account_kind"],
	):
		held.setdefault(a.sp_holder, {})[a.sp_account_kind.lower()] = a.name
	for u in users:
		u.keys = keys_of(roles.get(u.name, []))
		u.device = devices.get(u.name)
		u.accounts = held.get(u.name, {})
	return {
		"users": users,
		"keys": [
			{"key": r.key, "role": r.role_name, "label": r.label_ar, "light": not r.desk_access}
			for r in ROLES
		],
		"homes": [{"value": v, "label": _(HOME_LABELS.get(v, v))} for v in VARIANTS],
	}


# --- the actions --------------------------------------------------------------------------------


def _temporary_password() -> str:
	from smart_power.sp_core.login import temporary_password

	return temporary_password()


@frappe.whitelist(methods=["POST"])
def add_user(values: str | dict) -> dict:
	"""A new hire: the roles of the keys, the entry mode and home, and a temporary password."""
	_check_admin()
	values = frappe.parse_json(values) or {}
	email = (values.get("email") or "").strip().lower()
	if not email:
		frappe.throw(_("Enter the email the user signs in with."), frappe.MandatoryError)
	if frappe.db.exists(USER, email):
		frappe.throw(_("{0} already has an account.").format(email), frappe.DuplicateEntryError)
	keys = list(values.get("keys") or [])
	if not keys:
		frappe.throw(_("Give the user at least one role."), frappe.MandatoryError)
	first, _sep, last = (values.get("full_name") or "").strip().partition(" ")
	password = _temporary_password()
	user = frappe.get_doc(
		{
			"doctype": USER,
			"email": email,
			"first_name": first or email,
			"last_name": last or None,
			"mobile_no": (values.get("mobile_no") or "").strip() or None,
			"language": "ar",
			"send_welcome_email": 0,
			"sp_entry_mode": _mode(values.get("entry_mode")),
			"sp_home_page": _home(values.get("home")),
			"new_password": password,  # temporary: changed at the first sign-in (SP-36)
		}
	)
	user.append_roles(*sorted(_roles_for(keys)))
	user.insert(ignore_permissions=True)
	audit("User added", USER, user.name, keys=keys, entry_mode=user.sp_entry_mode, home=user.sp_home_page)
	return {"user": user.name, "password": password}


def _mode(mode: str | None) -> str:
	mode = (mode or "Full").capitalize()
	if mode not in ENTRY_MODES:
		frappe.throw(_("The entry mode is Full or Light."))
	return mode


def _home(home: str | None) -> str | None:
	from smart_power.dashboards.cards import VARIANTS

	if home and home not in VARIANTS:
		frappe.throw(_("Unknown home {0}.").format(frappe.bold(home)))
	return home or None


@frappe.whitelist(methods=["POST"])
def set_enabled(user: str, enabled: int | str) -> None:
	_check_admin()
	doc = _team_user(user)
	if doc.name == frappe.session.user and not int(enabled):
		frappe.throw(_("You cannot disable your own account."))
	doc.enabled = 1 if int(enabled) else 0
	doc.save(ignore_permissions=True)
	audit("User enabled" if doc.enabled else "User disabled", USER, doc.name)


@frappe.whitelist(methods=["POST"])
def set_roles(user: str, keys: str | list) -> list[str]:
	"""The user's role keys become exactly these; roles outside the catalogue are left alone."""
	_check_admin()
	doc = _team_user(user)
	keys = sorted(set(frappe.parse_json(keys) if isinstance(keys, str) else keys or []))
	before = keys_of(frappe.get_roles(doc.name))
	wanted = _roles_for(keys)
	managed = _given_by_catalogue()
	held = {r.role for r in doc.roles}
	if doc.name == frappe.session.user and "SP Admin" in held and "SP Admin" not in wanted:
		frappe.throw(_("You cannot take the admin role from yourself."))
	doc.set("roles", [r for r in doc.roles if r.role not in managed or r.role in wanted])
	doc.append_roles(*sorted(wanted - held))
	doc.save(ignore_permissions=True)
	audit(
		"Roles changed",
		USER,
		doc.name,
		given=sorted(set(keys) - set(before)),
		taken=sorted(set(before) - set(keys)),
	)
	return keys


@frappe.whitelist(methods=["POST"])
def set_home(user: str, home: str | None = None) -> None:
	"""The G2 home the user sees first (their own roles' other cards follow)."""
	_check_admin()
	doc = _team_user(user)
	frappe.db.set_value(USER, doc.name, "sp_home_page", _home(home))
	frappe.cache.delete_value(f"sp_home_cards:{doc.name}")
	audit("Home changed", USER, doc.name, home=home)


@frappe.whitelist(methods=["POST"])
def set_entry_mode(user: str, mode: str) -> None:
	_check_admin()
	doc = _team_user(user)
	frappe.db.set_value(USER, doc.name, "sp_entry_mode", _mode(mode))
	audit("Entry mode changed", USER, doc.name, mode=_mode(mode))


@frappe.whitelist(methods=["POST"])
def create_accounts(user: str, transit: int | str = 0, custody: int | str = 0) -> dict:
	"""The user's own transit and custody accounts (SP-113), for the company."""
	from smart_power.sp_finance.accounts import CUSTODY, TRANSIT, holder_account
	from smart_power.sp_finance.transfer import _company

	_check_admin()
	doc = _team_user(user)
	company = _company()
	made = {}
	if int(transit):
		made["transit"] = holder_account(doc.name, TRANSIT, company)
	if int(custody):
		made["custody"] = holder_account(doc.name, CUSTODY, company)
	audit("Accounts created", USER, doc.name, **made)
	return made


@frappe.whitelist(methods=["POST"])
def reset_password(user: str) -> str:
	"""A new temporary password, shown once; the account is unlocked."""
	_check_admin()
	doc = _team_user(user)
	password = _temporary_password()
	doc.new_password = password  # temporary: Must Change Password follows (SP-36)
	doc.sp_login_locked, doc.sp_failed_logins = 0, 0
	doc.save(ignore_permissions=True)
	audit("Password reset", USER, doc.name)
	return password


@frappe.whitelist(methods=["POST"])
def unlock(user: str) -> None:
	from smart_power.sp_core.login import unlock_login

	_check_admin()
	unlock_login(_team_user(user).name)
	audit("Login unlocked", USER, user)


@frappe.whitelist(methods=["POST"])
def revoke_device(device: str) -> None:
	"""The phone is off, and the user's API secret is replaced: its next sync gets 401."""
	_check_admin()
	row = frappe.get_doc(DEVICE, device)
	row.db_set({"active": 0, "revoked_on": now_datetime(), "revoked_by": frappe.session.user})
	user = frappe.get_doc(USER, row.user)
	user.api_secret = frappe.generate_hash(length=SECRET_LENGTH)
	user.save(ignore_permissions=True)
	audit("Device revoked", USER, row.user, device=row.device_id)
