"""X1 Users and roles (SP-130): a new hire with role keys and a home, unlock, and a revoked phone."""

import frappe
from frappe.auth import validate_api_key_secret
from frappe.tests import IntegrationTestCase
from frappe.utils.password import check_password

from smart_power.sp_core import users_roles as ur
from smart_power.sp_core.login import check_not_locked
from smart_power.sp_core.setup.role_catalogue import role
from smart_power.tests.utils import make_user

NEW_HIRE = "sp.ur.newhire@example.com"


class TestUsersRoles(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.admin = make_user("sp.ur.admin@example.com", ("admin",))
		cls.clerk = make_user("sp.ur.clerk@example.com", ("lead_intake",))

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")

	def as_admin(self, action, *args, **kwargs):
		frappe.set_user(self.admin)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def test_a_new_hire_gets_a_temporary_password_the_follow_up_roles_and_the_intake_home(self):
		from smart_power.dashboards.cards import get_home

		result = self.as_admin(
			ur.add_user,
			{
				"full_name": "موظف جديد",
				"email": NEW_HIRE,
				"keys": ["customer_followup", "lead_intake"],
				"home": "intake",
				"entry_mode": "Full",
			},
		)
		self.assertEqual(result["user"], NEW_HIRE)
		self.assertEqual(check_password(NEW_HIRE, result["password"]), NEW_HIRE)  # the login works
		user = frappe.get_doc("User", NEW_HIRE)
		self.assertEqual(user.sp_must_change_password, 1)  # changed at the first sign-in
		self.assertTrue({role("customer_followup"), role("lead_intake")} <= set(frappe.get_roles(NEW_HIRE)))
		self.assertTrue(frappe.has_permission("SP Case", "read", user=NEW_HIRE))  # the follow-up menu
		frappe.set_user(NEW_HIRE)
		home = get_home()
		frappe.set_user("Administrator")
		self.assertEqual((home["home"], home["variants"][0]), ("intake", "intake"))
		self.assertTrue(
			frappe.db.exists("SP Audit Log", {"action": "User added", "reference_name": NEW_HIRE})
		)

	def test_roles_are_given_and_taken_by_key_and_only_by_the_admin(self):
		self.as_admin(ur.set_roles, self.clerk, ["customer_followup"])
		roles = set(frappe.get_roles(self.clerk))
		self.assertIn(role("customer_followup"), roles)
		self.assertNotIn(role("lead_intake"), roles)
		frappe.set_user(self.clerk)
		with self.assertRaises(frappe.PermissionError):
			ur.set_roles(self.clerk, ["admin"])
		frappe.set_user("Administrator")

	def test_a_locked_user_can_sign_in_again_after_unlock(self):
		frappe.db.set_value("User", self.clerk, {"sp_login_locked": 1, "sp_failed_logins": 5})
		with self.assertRaises(frappe.AuthenticationError):
			check_not_locked(self.clerk)
		self.as_admin(ur.unlock, self.clerk)
		check_not_locked(self.clerk)  # no longer refused
		self.assertEqual(frappe.db.get_value("User", self.clerk, "sp_failed_logins"), 0)

	def test_a_revoked_device_gets_401_on_its_next_sync(self):
		user = frappe.get_doc("User", self.clerk)
		user.api_key = frappe.generate_hash(length=15)
		secret = frappe.generate_hash(length=15)
		user.api_secret = secret
		user.save(ignore_permissions=True)
		device = frappe.get_doc(
			{"doctype": ur.DEVICE, "user": self.clerk, "device_id": "SP130-PHONE", "active": 1}
		).insert(ignore_permissions=True)
		self.as_admin(ur.revoke_device, device.name)
		self.assertEqual(frappe.db.get_value(ur.DEVICE, device.name, "active"), 0)
		with self.assertRaises(frappe.AuthenticationError):  # Frappe answers 401
			validate_api_key_secret(user.api_key, secret)
