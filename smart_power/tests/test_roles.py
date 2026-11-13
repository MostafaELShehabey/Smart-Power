"""Role catalogue, person profiles and the light-entry redirect (SP-34)."""

from types import SimpleNamespace

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.routing import RequestRedirect

from smart_power.sp_core.setup.role_catalogue import BY_KEY, PROFILES, ROLES, role
from smart_power.sp_core.web import redirect_light_users
from smart_power.tests.utils import make_user


class TestRoles(IntegrationTestCase):
	def test_catalogue_has_37_keys_and_all_roles_exist(self):
		# 36 keys from the Miro board, plus followup_all (SP-35)
		self.assertEqual(len(ROLES), 37)
		for r in ROLES:
			self.assertTrue(frappe.db.exists("Role", r.role_name), r.role_name)
			self.assertEqual(frappe.db.get_value("Role", r.role_name, "desk_access"), int(r.desk_access))

	def test_only_drivers_have_no_desk(self):
		no_desk = {r.key for r in ROLES if not r.desk_access}
		self.assertEqual(no_desk, {"driver", "winch_operator"})

	def test_technical_office_profile_has_exactly_its_roles(self):
		"""Given the profile, then Aya has exactly her SP roles (Miro team table, 8-11)."""
		profile = frappe.get_doc("Role Profile", "SP Technical Office")
		sp_roles = {r.role for r in profile.roles if r.role.startswith("SP ")}
		expected = {
			role(k)
			for k in (
				"quote_creator",
				"receipt_confirmer",
				"catalog_manager",
				"pricing_manager",
				"regulatory_compliance",
				"custody_holder",
			)
		}
		self.assertEqual(sp_roles, expected)
		self.assertIn("Sales User", {r.role for r in profile.roles})

	def test_every_profile_matches_the_catalogue(self):
		for p in PROFILES:
			doc = frappe.get_doc("Role Profile", p.name)
			self.assertEqual({r.role for r in doc.roles}, set(p.roles()), p.name)

	def test_new_hire_gets_followup_by_roles_not_by_person(self):
		user = make_user("sp.newhire@example.com", ("customer_followup", "lead_intake"))
		roles = set(frappe.get_roles(user))
		self.assertTrue({role("customer_followup"), role("lead_intake"), "Sales User"} <= roles)
		self.assertEqual(frappe.db.get_value("User", user, "user_type"), "System User")


class TestLightEntryRedirect(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.driver = make_user("sp.driver@example.com", ("driver",))

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.request = None

	def _request(self, path):
		frappe.local.request = SimpleNamespace(method="GET", path=path)

	def test_driver_is_a_website_user(self):
		self.assertEqual(frappe.db.get_value("User", self.driver, "user_type"), "Website User")

	def test_driver_opening_the_desk_goes_to_the_field_page(self):
		frappe.set_user(self.driver)
		frappe.session.data.user_type = "Website User"
		self._request("/desk/quotation")
		with self.assertRaises(RequestRedirect) as ctx:
			redirect_light_users()
		self.assertTrue(ctx.exception.new_url.endswith("/sp-field"))

	def test_office_user_is_not_redirected(self):
		frappe.set_user("Administrator")
		frappe.session.data.user_type = "System User"
		self._request("/desk")
		redirect_light_users()

	def test_home_page_hook_points_drivers_to_the_field_page(self):
		home = frappe.get_hooks("role_home_page")
		self.assertEqual(home[role("driver")][-1], "sp-field")
		self.assertEqual(home[BY_KEY["winch_operator"].role_name][-1], "sp-field")
