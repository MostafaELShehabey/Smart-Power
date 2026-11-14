"""The field page for drivers and the winch operator (SP-34)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.website.serve import get_response, get_response_content

from smart_power.tests.utils import make_user


class TestFieldPage(IntegrationTestCase):
	def setUp(self):
		# CI skips building assets; the web page shell looks bundles up in assets.json
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)

	def test_page_greets_the_user_by_name(self):
		user = make_user("sp.field.driver@example.com", ("driver",))
		name = frappe.utils.get_fullname(user)
		frappe.set_user(user)
		try:
			html = get_response_content("sp-field")
		finally:
			frappe.set_user("Administrator")
		self.assertIn(name, html)  # in the greeting, whatever the language
		self.assertNotIn("{{ full_name }}", html)

	def test_guests_are_sent_to_log_in(self):
		frappe.set_user("Guest")
		try:
			response = get_response("sp-field")
		finally:
			frappe.set_user("Administrator")
		self.assertIn(response.status_code, (301, 302, 303, 307, 308))
		self.assertIn("/login", response.headers.get("Location", ""))
