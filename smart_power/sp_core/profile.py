"""G6 Profile (SP-42): my roles (read-only), language, notification channels, my custody and the
cash I hold, change password.

- Roles: the SP roles with their Arabic names; nobody edits their own roles here.
- Language: Arabic (right to left) or English; the Desk reloads in it.
- Notification channels: in-app and email, from Frappe's own Notification Settings of the user
  (the per-event preferences come with Notifications G4, SP-40).
- Money: only my own transit and custody accounts (SP-26), with the balance and the days held
  since the oldest money not yet spent or deposited; red past the limit (X6 for cash held, or
  the account's own Max Days Held).
- Password: Frappe's own change (the old password is checked).
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, today

LANGUAGES = ("ar", "en")
CHANNELS = {"in_app": "enabled", "email": "enable_email_notifications"}


def _roles(user: str, language: str) -> list[dict]:
	"""My SP roles: their Arabic names, or the role names in English."""
	from smart_power.sp_core.setup.role_catalogue import ROLES

	mine = set(frappe.get_roles(user))
	return [
		{"role": r.role_name, "label": r.label_ar if language == "ar" else r.role_name.removeprefix("SP ")}
		for r in ROLES
		if r.role_name in mine
	]


def _money(user: str) -> list[dict]:
	"""My transit and custody accounts: balance, days held, and whether past the limit."""
	from erpnext.accounts.utils import get_balance_on

	from smart_power.sp_finance.accounts import HOLDER_KINDS, TRANSIT
	from smart_power.sp_finance.transit import days_held, limit_days, oldest_open_date

	out = []
	for r in frappe.get_all(
		"Account",
		{"sp_holder": user, "sp_account_kind": ("in", HOLDER_KINDS), "is_group": 0, "disabled": 0},
		["name", "account_name", "sp_account_kind", "company", "sp_max_days_held"],
		order_by="sp_account_kind desc, account_name asc",
	):
		balance = flt(get_balance_on(r.name, company=r.company, ignore_account_permission=True))
		if r.sp_account_kind == TRANSIT:
			# cash held counts the day it came in (SP-116), against the X6 limit
			held, limit = days_held(r.name), limit_days(r.name)
		else:
			oldest = oldest_open_date(r.name)
			held, limit = (date_diff(today(), oldest) if oldest else 0), flt(r.sp_max_days_held)
		out.append(
			{
				"account": r.name,
				"account_name": r.account_name,
				"kind": r.sp_account_kind,
				"balance": balance,
				"days_held": held if balance > 0 else 0,
				"limit": limit,
				"over": bool(limit and balance > 0 and held > limit),
			}
		)
	return out


def _settings(user: str):
	if not frappe.db.exists("Notification Settings", user):
		from frappe.desk.doctype.notification_settings.notification_settings import (
			create_notification_settings,
		)

		create_notification_settings(user)
	return frappe.get_doc("Notification Settings", user)


@frappe.whitelist()
def profile() -> dict:
	"""Everything the G6 page shows, for the signed-in user only."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Sign in first."), frappe.PermissionError)
	doc = frappe.get_doc("User", user)
	settings = _settings(user)
	language = doc.language or frappe.db.get_default("lang") or "ar"
	return {
		"user": user,
		"full_name": doc.full_name,
		"email": doc.email,
		"mobile": doc.mobile_no,
		"image": doc.user_image,
		"language": language,
		"roles": _roles(user, language),
		"channels": {key: bool(settings.get(field)) for key, field in CHANNELS.items()},
		"money": _money(user),
	}


@frappe.whitelist(methods=["POST"])
def set_language(language: str) -> str:
	"""Arabic or English; the page reloads the Desk in it."""
	if language not in LANGUAGES:
		frappe.throw(_("Choose Arabic or English."))
	frappe.db.set_value("User", frappe.session.user, "language", language)
	frappe.clear_cache(user=frappe.session.user)
	return language


@frappe.whitelist(methods=["POST"])
def set_channels(channels: str | dict) -> dict:
	"""My notification channels (in-app, email)."""
	channels = frappe.parse_json(channels) or {}
	settings = _settings(frappe.session.user)
	for key, field in CHANNELS.items():
		if key in channels:
			settings.set(field, 1 if channels[key] else 0)
	settings.flags.ignore_permissions = True  # the user's own settings
	settings.save()
	return {key: bool(settings.get(field)) for key, field in CHANNELS.items()}
