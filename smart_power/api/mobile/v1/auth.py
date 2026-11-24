"""auth.login / logout / register_push (SP-148). The token is the user's API key and secret
(SP-130): revoking a phone replaces the secret, so its next call gets 401. A new phone works at
once and is listed for the admin (owner's decision 24-11-2026)."""

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import check_password, get_decrypted_password

from smart_power.api.mobile.v1.common import DEVICE, answer_error, device_id, endpoint, fail
from smart_power.sp_core import login as sp_login

SECRET_LENGTH = 15  # sp-allow-number: the length Frappe's own key generation uses


def _token(user: str) -> str:
	doc = frappe.get_doc("User", user)
	changed = False
	if not doc.api_key:
		doc.api_key = frappe.generate_hash(length=SECRET_LENGTH)
		changed = True
	secret = (
		get_decrypted_password("User", user, "api_secret", raise_exception=False) if not changed else None
	)
	if not secret:
		secret = frappe.generate_hash(length=SECRET_LENGTH)
		doc.api_secret = secret
		changed = True
	if changed:
		doc.save(ignore_permissions=True)
	return f"{doc.api_key}:{secret}"


def _register(user: str, device: str | None, name: str | None) -> None:
	if not device:
		return
	row = frappe.db.get_value(
		DEVICE, {"user": user, "device_id": device}, ["name", "revoked_on"], as_dict=True
	)
	if row and row.revoked_on:
		fail("DEVICE_REVOKED", _("This phone was turned off by the admin."))
	if row:
		frappe.db.set_value(DEVICE, row.name, {"active": 1, "last_sync": now_datetime()})
	else:
		frappe.get_doc(
			{
				"doctype": DEVICE,
				"user": user,
				"device_id": device,
				"device_name": name,
				"active": 1,
				"last_sync": now_datetime(),
			}
		).insert(ignore_permissions=True)


@endpoint(methods=("POST",), allow_guest=True)
def login(usr: str, pwd: str, device_name: str | None = None) -> dict:
	"""Email or mobile and password → the token. A locked account, a wrong password (counted
	toward the lock) and a password still to change are refused."""
	user = sp_login.find_user(sp_login.login_name(usr))
	sp_login.check_not_locked(usr)
	try:
		check_password(user or usr, pwd)
	except frappe.AuthenticationError:
		if user:
			# counted toward the lock as the desk counts it: answered without undoing the count
			sp_login.on_failed_login(frappe._dict(operation="Login", status="Failed", user=user))
		return answer_error("AUTH", _("Wrong mobile, email or password."))
	if sp_login.must_change(user):
		fail("PASSWORD_CHANGE", _("Change your password on the website first."))
	frappe.db.set_value("User", user, "sp_failed_logins", 0, update_modified=False)
	_register(user, device_id(), device_name)
	doc = frappe.get_cached_doc("User", user)
	return {"token": _token(user), "user": user, "full_name": doc.full_name, "language": doc.language or "ar"}


@endpoint(methods=("POST",))
def logout() -> dict:
	"""This phone is signed out (not revoked: signing in again works)."""
	device = device_id()
	name = device and frappe.db.get_value(DEVICE, {"user": frappe.session.user, "device_id": device})
	if name:
		frappe.db.set_value(DEVICE, name, "active", 0)
	return {"ok": True}


@endpoint(methods=("POST",))
def register_push(fcm_token: str) -> dict:
	"""The phone's push token, for SP-149's push messages."""
	device = device_id()
	name = device and frappe.db.get_value(DEVICE, {"user": frappe.session.user, "device_id": device})
	if not name:
		fail("VALIDATION", _("Sign in from this phone first."))
	frappe.db.set_value(DEVICE, name, "fcm_token", fcm_token)
	return {"ok": True}
