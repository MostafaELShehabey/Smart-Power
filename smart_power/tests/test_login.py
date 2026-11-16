"""Login (SP-36, G1): mobile or email; the lock after failed tries; the first-login password change."""

import frappe
from frappe.auth import CookieManager, LoginManager
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request
from werkzeug.routing import RequestRedirect

from smart_power.sp_core.login import apply_login_settings, guard_first_login, unlock_login, update_password
from smart_power.tests.utils import set_setting

PASSWORD = "Sp-36 login test 7391"  # a test value for this test user only
MOBILE = "01012345678"


def login(usr: str, pwd: str = PASSWORD) -> str:
	"""Sign in as a browser would; returns the signed-in user (raises AuthenticationError)."""
	set_request(path="/api/method/login")
	frappe.local.request_ip = "127.0.0.1"
	frappe.local.cookie_manager = CookieManager()
	frappe.form_dict.update({"cmd": "login", "usr": usr, "pwd": pwd})
	frappe.local.login_manager = LoginManager()  # signs in on the login path
	return frappe.session.user


def make_login_user(email: str, mobile: str | None = None) -> str:
	"""A desk user with a known password. Deleted by the test's cleanup: a failed login commits."""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"mobile_no": mobile,
				"new_password": PASSWORD,
				"send_welcome_email": 0,
				"roles": [{"role": "SP Lead Intake"}],
			}
		).insert(ignore_permissions=True)
	return email


def drop_user(email: str) -> None:
	frappe.set_user("Administrator")
	frappe.db.delete("Sessions", {"user": email})
	frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	frappe.db.commit()


class LoginCase(IntegrationTestCase):
	EMAIL = "sp.login.user@example.com"

	def setUp(self):
		apply_login_settings()
		self.user = make_login_user(self.EMAIL, "+20 101 234 5678")
		self.addCleanup(drop_user, self.EMAIL)

	def tearDown(self):
		frappe.set_user("Administrator")


class TestMobileLogin(LoginCase):
	def test_the_mobile_is_kept_in_its_local_form(self):
		self.assertEqual(frappe.db.get_value("User", self.user, "mobile_no"), MOBILE)

	def test_a_user_signs_in_with_mobile_or_email(self):
		self.assertEqual(login(MOBILE), self.user)
		self.assertEqual(login("+20 101 234 5678"), self.user)  # typed with the country code
		self.assertEqual(login(self.EMAIL), self.user)
		with self.assertRaises(frappe.AuthenticationError):
			login(MOBILE, "wrong password")


class TestLoginLock(LoginCase):
	EMAIL = "sp.login.locked@example.com"

	def setUp(self):
		super().setUp()
		from smart_power.tests.utils import make_user

		self.admin = make_user("sp.login.admin@example.com", ("admin",))
		set_setting(login_lock_attempts=5)

	def test_five_wrong_passwords_lock_the_account_until_the_admin_unlocks_it(self):
		for _attempt in range(5):  # sp-allow-number: the acceptance check's five tries
			with self.assertRaises(frappe.AuthenticationError):
				login(MOBILE, "wrong password")
		self.assertTrue(frappe.db.get_value("User", self.user, "sp_login_locked"))
		with self.assertRaises(frappe.AuthenticationError) as refused:
			login(MOBILE)  # the 6th try, even with the right password
		self.assertIn("contact the admin", str(refused.exception))
		alert = frappe.db.exists(
			"Notification Log",
			{"for_user": self.admin, "document_name": self.user, "sp_event": "login_locked"},
		)
		self.assertTrue(alert, "the admin sees a lock alert")
		frappe.set_user(self.admin)
		unlock_login(self.user)
		frappe.set_user("Administrator")
		self.assertEqual(login(MOBILE), self.user)

	def test_a_success_clears_the_count_and_only_the_admin_unlocks(self):
		with self.assertRaises(frappe.AuthenticationError):
			login(MOBILE, "wrong password")
		self.assertEqual(frappe.db.get_value("User", self.user, "sp_failed_logins"), 1)
		login(MOBILE)
		self.assertEqual(frappe.db.get_value("User", self.user, "sp_failed_logins"), 0)
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			unlock_login(self.user)


class TestFirstLogin(LoginCase):
	EMAIL = "sp.login.first@example.com"

	def request(self, path: str):
		set_request(path=path)
		frappe.set_user(self.user)
		try:
			guard_first_login()
		finally:
			frappe.set_user("Administrator")

	def test_a_new_user_must_set_a_new_password_before_any_other_page(self):
		self.assertTrue(frappe.db.get_value("User", self.user, "sp_must_change_password"))
		with self.assertRaises(RequestRedirect) as redirect:
			self.request("/desk")
		self.assertIn("/update-password", redirect.exception.new_url)
		with self.assertRaises(frappe.PermissionError):
			self.request("/api/method/frappe.client.get_list")
		self.request("/update-password")  # the one page left open
		self.request("/api/method/frappe.core.doctype.user.user.test_password_strength")
		login(MOBILE)  # signed in, as on the update-password page
		update_password("A brand new SP-36 phrase 5280", old_password=PASSWORD)
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.get_value("User", self.user, "sp_must_change_password"))
		self.request("/desk")  # no longer sent away

	def test_a_password_the_admin_sets_is_temporary(self):
		frappe.db.set_value("User", self.user, "sp_must_change_password", 0)
		user = frappe.get_doc("User", self.user)
		user.new_password = "Admin given SP-36 phrase 6614"
		user.save(ignore_permissions=True)
		self.assertTrue(frappe.db.get_value("User", self.user, "sp_must_change_password"))
