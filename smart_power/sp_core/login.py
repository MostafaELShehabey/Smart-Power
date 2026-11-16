"""Login (SP-36, G1): mobile or email, a lock after failed tries, reset through the admin, and a
password change at the first login.

- A user signs in with their email or their mobile (01xxxxxxxxx, also typed as +20 or 0020).
  The mobile is stored in that local form, so it matches; Frappe keeps it unique.
- Failed sign-ins are counted on the user; Login Lock Attempts (5) in a row lock the account
  until the admin unlocks it, and the admins get an alert. The lock is kept on the user, not
  Frappe's timed cache lock, which would also lock a shared office IP.
- A password someone else gave (a new user, the admin's reset) must be changed at the first
  login: until then every page leads to /update-password and the API refuses.
- Forgot password (email or mobile) sends a request to the admin, never an email: the admin
  gives a temporary password from the request, which also unlocks the account.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint

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
	"""before_login: a mobile typed as +20 or with spaces still finds the user; a locked account
	is refused before its password is even checked."""
	usr = frappe.form_dict.get("usr")
	if usr:
		frappe.form_dict.usr = login_name(usr)
		check_not_locked(frappe.form_dict.usr)


# --- the lock after failed tries ---------------------------------------------------------------

LOCK_SETTING, LOCK_DEFAULT = "login_lock_attempts", 5  # sp-allow-number: the seed's value, if unset
ADMIN_ROLES = ("SP Admin", "System Manager")
HTTP_GONE = 410  # sp-allow-number: Frappe's answer to a wrong old password or an expired key


def lock_attempts() -> int:
	from smart_power.sp_core.services.settings import get_value

	return cint(get_value(LOCK_SETTING, LOCK_DEFAULT)) or LOCK_DEFAULT


def find_user(login: str | None) -> str | None:
	"""The user an email or mobile signs in as."""
	if not login:
		return None
	return frappe.db.get_value("User", login) or frappe.db.get_value("User", {"mobile_no": login_name(login)})


def check_not_locked(login: str | None) -> None:
	user = find_user(login)
	if user and frappe.db.get_value("User", user, "sp_login_locked"):
		frappe.throw(_("Account locked — contact the admin"), frappe.AuthenticationError)


def on_failed_login(doc, method=None) -> None:
	"""Activity Log after_insert: a failed sign-in counts; that many in a row lock the account."""
	if doc.operation != "Login" or doc.status != "Failed":
		return
	user = doc.user
	if not user or user in frappe.STANDARD_USERS or not frappe.db.exists("User", user):
		return
	failed = cint(frappe.db.get_value("User", user, "sp_failed_logins")) + 1
	values = {"sp_failed_logins": failed}
	locked = failed >= lock_attempts() and not frappe.db.get_value("User", user, "sp_login_locked")
	if locked:
		values["sp_login_locked"] = 1
	frappe.db.set_value("User", user, values, update_modified=False)
	if locked:
		_alert_admins(user, failed)


def _alert_admins(user: str, failed: int) -> None:
	from smart_power.notify import send
	from smart_power.sp_sales.quote_request import _users_with

	admins = {u for role in ADMIN_ROLES for u in _users_with(role)} - {"Administrator"}
	subject = _("{0} is locked after {1} failed sign-ins.").format(frappe.utils.get_fullname(user), failed)
	send("login_locked", admins, "User", user, subject)


def on_login(login_manager=None) -> None:
	"""on_login: a successful sign-in clears the failed count."""
	user = getattr(login_manager, "user", None) or frappe.session.user
	if user and cint(frappe.db.get_value("User", user, "sp_failed_logins")):
		frappe.db.set_value("User", user, "sp_failed_logins", 0, update_modified=False)


@frappe.whitelist(methods=["POST"])
def unlock_login(user: str) -> None:
	"""The admin unlocks an account locked by failed sign-ins."""
	if frappe.session.user != "Administrator" and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin unlocks an account."), frappe.PermissionError)
	frappe.db.set_value("User", user, {"sp_login_locked": 0, "sp_failed_logins": 0})


# --- the password change at the first login ----------------------------------------------------

UPDATE_PASSWORD = "/update-password"
# what a user who must change their password may still reach
OPEN_PATHS = (
	UPDATE_PASSWORD,
	"/api/method/frappe.core.doctype.user.user.update_password",
	"/api/method/frappe.core.doctype.user.user.test_password_strength",
	"/api/method/login",
	"/api/method/logout",
	"/login",
	"/assets/",
	"/files/",
	"/website_script.js",
)


def set_must_change(doc, method=None) -> None:
	"""User before_validate: a password given by someone else (a new user, the admin's reset) is
	temporary; the user's own new password is not."""
	if doc.name in frappe.STANDARD_USERS or doc.get("user_type") == "Website User":
		return
	if doc.is_new():
		doc.sp_must_change_password = 1
	elif doc.get("new_password"):
		doc.sp_must_change_password = 0 if frappe.session.user == doc.name else 1


def must_change(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not user or user in frappe.STANDARD_USERS:
		return False
	return bool(frappe.get_cached_value("User", user, "sp_must_change_password"))


def guard_first_login() -> None:
	"""before_request: until they change their password, a user reaches nothing else."""
	from werkzeug.routing import RequestRedirect

	request = getattr(frappe.local, "request", None)
	if not request or not must_change() or request.path.startswith(OPEN_PATHS):
		return
	if request.path.startswith("/api/"):
		frappe.throw(_("Change your password first."), frappe.PermissionError)
	raise RequestRedirect(UPDATE_PASSWORD)


# Guest, as Frappe's own update_password is (the reset-key flow); it only delegates to it.
@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
def update_password(
	new_password: str, logout_all_sessions: int = 0, key: str | None = None, old_password: str | None = None
):
	"""Frappe's update_password; a successful change clears Must Change Password."""
	from frappe.core.doctype.user.user import update_password as frappe_update_password

	result = frappe_update_password(new_password, logout_all_sessions, key, old_password)
	user = frappe.session.user
	if frappe.local.response.get("http_status_code") != HTTP_GONE and must_change(user):
		frappe.db.set_value("User", user, "sp_must_change_password", 0)
		frappe.clear_document_cache("User", user)
	return result


# --- Forgot password: a request to the admin --------------------------------------------------

RESET_REQUEST = "SP Password Reset Request"
RESET_LIMIT, RESET_WINDOW = 5, 60 * 60  # sp-allow-number: requests per hour from one address
GROUP, GROUPS = 4, 3  # sp-allow-number: the temporary password's shape (3 groups of 4)


# Guest: the login page's Forgot password, before anyone is signed in; rate-limited.
@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep
@rate_limit(limit=RESET_LIMIT, seconds=RESET_WINDOW)
def request_password_reset(user: str) -> None:
	"""Forgot password (email or mobile): a request to the admin, who gives a temporary password.

	The answer is the same whether or not the account exists, so it tells nothing about it."""
	name = find_user((user or "").strip())
	if name and name not in frappe.STANDARD_USERS and frappe.db.get_value("User", name, "enabled"):
		open_request = frappe.db.exists(RESET_REQUEST, {"user": name, "status": "Open"})
		if not open_request:
			doc = frappe.get_doc(
				{
					"doctype": RESET_REQUEST,
					"user": name,
					"typed": user,
					"requested_on": frappe.utils.now_datetime(),
				}
			).insert(ignore_permissions=True)
			_notify_reset(doc)
	frappe.msgprint(
		_("Your request was sent to the admin, who will give you a new password."),
		title=_("Forgot password"),
	)


def _notify_reset(doc) -> None:
	from smart_power.notify import send
	from smart_power.sp_core.inbox import create_task
	from smart_power.sp_sales.quote_request import _users_with

	admins = {u for role in ADMIN_ROLES for u in _users_with(role)} - {"Administrator"}
	subject = _("{0} forgot their password.").format(frappe.utils.get_fullname(doc.user))
	send("password_reset", admins, RESET_REQUEST, doc.name, subject)
	create_task("Password Reset", RESET_REQUEST, doc.name, admins or ["Administrator"], subject)


@frappe.whitelist(methods=["POST"])
def give_temporary_password(request: str) -> str:
	"""The admin gives a temporary password: the account is unlocked, the user changes the password
	at their next sign-in. The password is returned once, for the admin to pass on."""
	if frappe.session.user != "Administrator" and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin resets a password."), frappe.PermissionError)
	doc = frappe.get_doc(RESET_REQUEST, request)
	if doc.status != "Open":
		frappe.throw(_("This request is already handled."))
	password = temporary_password()
	user = frappe.get_doc("User", doc.user)
	user.new_password = password  # given by the admin: Must Change Password follows (set_must_change)
	user.sp_login_locked, user.sp_failed_logins = 0, 0
	user.save(ignore_permissions=True)
	doc.db_set(
		{"status": "Done", "handled_by": frappe.session.user, "handled_on": frappe.utils.now_datetime()}
	)
	from smart_power.sp_core.inbox import close_tasks

	close_tasks(RESET_REQUEST, doc.name)
	return password


def temporary_password() -> str:
	"""Readable and strong enough for the password policy: e.g. Sp-4kq9-x2mf-7tbw."""
	import secrets
	import string

	alphabet = string.ascii_lowercase + string.digits
	groups = ("".join(secrets.choice(alphabet) for _i in range(GROUP)) for _g in range(GROUPS))
	return "Sp-" + "-".join(groups)
