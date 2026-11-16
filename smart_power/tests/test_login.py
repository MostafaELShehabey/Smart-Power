"""Login (SP-36, G1): mobile or email."""

import frappe
from frappe.auth import CookieManager, LoginManager
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request

from smart_power.sp_core.login import apply_login_settings

PASSWORD = "Sp-36 login test 7391"  # a test value for this test user only
MOBILE = "01012345678"


def login(usr: str, pwd: str = PASSWORD) -> str:
	"""Sign in as a browser would; returns the signed-in user (raises AuthenticationError)."""
	set_request(path="/api/method/login")
	frappe.local.request_ip = "127.0.0.1"
	frappe.local.cookie_manager = CookieManager()
	frappe.form_dict.update({"cmd": "login", "usr": usr, "pwd": pwd})
	LoginManager()  # signs in on the login path
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
