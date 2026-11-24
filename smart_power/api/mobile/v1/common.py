"""The mobile API v1 (SP-148): what every endpoint shares.

    @endpoint(...)    whitelists the function, checks the phone and the rate, and turns errors into
                      {"error": {code, message_ar, details}} with a stable code and HTTP status
    safe(row)         a dict without any money key (price, cost, amount, rate, …)

Codes: AUTH (401), DEVICE_REVOKED (401), PASSWORD_CHANGE (403), NOT_PERMITTED (403),
NOT_FOUND (404), VALIDATION (417), DAY_LOCKED (423), RATE_LIMITED (429). v1 is frozen after
go-live: a breaking change goes to v2.
"""

import functools
import time
from http import HTTPStatus

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

DEVICE = "SP Mobile Device"
DEVICE_HEADER = "X-SP-Device"
SAVEPOINT = "sp_mobile_call"
RATE_SETTING, RATE_DEFAULT = "mobile_rate_limit", 120  # sp-allow-number: the story's 120 a minute
WINDOW = 60  # sp-allow-number: seconds in the rate window
HTTP = {
	"AUTH": HTTPStatus.UNAUTHORIZED,
	"DEVICE_REVOKED": HTTPStatus.UNAUTHORIZED,
	"PASSWORD_CHANGE": HTTPStatus.FORBIDDEN,
	"NOT_PERMITTED": HTTPStatus.FORBIDDEN,
	"NOT_FOUND": HTTPStatus.NOT_FOUND,
	"VALIDATION": HTTPStatus.EXPECTATION_FAILED,
	"DAY_LOCKED": HTTPStatus.LOCKED,
	"RATE_LIMITED": HTTPStatus.TOO_MANY_REQUESTS,
}
# a key with one of these parts is money (payment_amount, sp_cost, base_rate, price_list_rate)
MONEY_WORDS = {
	"price",
	"cost",
	"amount",
	"rate",
	"profit",
	"margin",
	"paid",
	"commission",
	"outstanding",
	"money",
}


class MobileError(Exception):
	def __init__(self, code: str, message: str, details=None):
		super().__init__(message)
		self.code, self.message, self.details = code, message, details


def fail(code: str, message: str, details=None):
	raise MobileError(code, message, details)


def answer_error(code: str, message: str, details=None) -> dict:
	"""The error answer, keeping what the call wrote (a failed sign-in's count)."""
	frappe.clear_messages()
	frappe.local.response.http_status_code = int(HTTP.get(code, HTTP["VALIDATION"]))
	return {"error": {"code": code, "message_ar": message, "details": details}}


def _error(code: str, message: str, details=None) -> dict:
	"""The error answer after undoing what the call wrote (back to its savepoint)."""
	frappe.db.rollback(save_point=SAVEPOINT)
	return answer_error(code, message, details)


def _message(exc) -> str:
	return frappe.utils.strip_html(str(exc)) or _("Something went wrong.")


def device_id() -> str | None:
	return frappe.get_request_header(DEVICE_HEADER) if frappe.request else None


def check_device() -> None:
	"""A phone the admin turned off gets DEVICE_REVOKED, even before its token is replaced."""
	device = device_id()
	if not device:
		return
	row = frappe.db.get_value(
		DEVICE, {"user": frappe.session.user, "device_id": device}, ["name", "revoked_on"], as_dict=True
	)
	if row and row.revoked_on:
		fail("DEVICE_REVOKED", _("This phone was turned off by the admin."))


def rate_key(user: str | None = None) -> str:
	"""This minute's counter of the user's calls."""
	return f"sp_mobile_rate|{frappe.local.site}|{user or frappe.session.user}|{int(time.time() // WINDOW)}"


def check_rate() -> None:
	"""At most Mobile Rate Limit calls a minute per user (120): the next one gets 429."""
	from smart_power.sp_core.services.settings import get_value

	limit = cint(get_value(RATE_SETTING)) or RATE_DEFAULT
	key = rate_key()
	count = frappe.cache.incr(key)
	if count == 1:
		frappe.cache.expire(key, WINDOW * 2)  # sp-allow-number: past the window, then gone
	if count > limit:
		fail("RATE_LIMITED", _("Too many requests: wait a minute and try again."), {"limit": limit})


def endpoint(methods=("GET", "POST"), allow_guest: bool = False):
	def wrap(fn):
		@functools.wraps(fn)
		def call(*args, **kwargs):
			frappe.db.savepoint(SAVEPOINT)
			if frappe.session.user == "Guest":
				frappe.local.lang = "ar"  # the app is Arabic: message_ar before anyone signs in
			try:
				if not allow_guest:
					if frappe.session.user == "Guest":
						fail("AUTH", _("Sign in first."))
					check_device()
					check_rate()
				return fn(*args, **kwargs)
			except MobileError as e:
				return _error(e.code, e.message, e.details)
			except frappe.AuthenticationError as e:
				return _error("AUTH", _message(e))
			except frappe.PermissionError as e:
				return _error("NOT_PERMITTED", _message(e) or _("Not permitted."))
			except frappe.DoesNotExistError as e:
				return _error("NOT_FOUND", _message(e))
			except frappe.ValidationError as e:
				return _error("VALIDATION", _message(e))

		# open to guests at Frappe's door so a call without a token gets this API's AUTH (401)
		# answer; the first thing call() does is refuse a guest on a signed-in endpoint
		return frappe.whitelist(allow_guest=True, methods=list(methods))(call)

	return wrap


def is_money(key: str) -> bool:
	return bool(set(str(key or "").lower().split("_")) & MONEY_WORDS)


def safe(value):
	"""The value with every money key removed, at any depth."""
	if isinstance(value, dict):
		return {k: safe(v) for k, v in value.items() if not is_money(k)}
	if isinstance(value, list | tuple):
		return [safe(v) for v in value]
	return value


def touch_device() -> None:
	device = device_id()
	if device:
		name = frappe.db.get_value(DEVICE, {"user": frappe.session.user, "device_id": device})
		if name:
			frappe.db.set_value(DEVICE, name, "last_sync", now_datetime(), update_modified=False)
