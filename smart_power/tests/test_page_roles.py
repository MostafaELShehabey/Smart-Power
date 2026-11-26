"""Every Smart Power page keeps the roles its file names (BUG-33).

A page with no role rows is open to every desk user: its menu item shows and the page opens.
Migrate re-reads a page file only when the file's `modified` is newer than the site's, so roles
added to a file without a new `modified` never reach a site that already has the page.
"""

import glob
import json
import os

import frappe
from frappe.tests import IntegrationTestCase


def page_files() -> list[dict]:
	pattern = os.path.join(frappe.get_app_path("smart_power"), "*", "page", "*", "*.json")
	return [json.load(open(path, encoding="utf-8")) for path in sorted(glob.glob(pattern))]


class TestPageRoles(IntegrationTestCase):
	def test_every_page_has_the_roles_of_its_file(self):
		pages = page_files()
		self.assertTrue(pages)
		for page in pages:
			with self.subTest(page=page["name"]):
				on_site = frappe.get_all(
					"Has Role", {"parent": page["name"], "parenttype": "Page"}, pluck="role"
				)
				self.assertEqual(sorted(on_site), sorted(row["role"] for row in page.get("roles", [])))

	def test_the_media_library_is_for_marketing(self):
		roles = {r.role for r in frappe.get_doc("Page", "sp-media-library").roles}
		self.assertEqual(roles, {"SP Marketing Agent", "SP Admin", "System Manager"})

	def test_my_custody_is_for_holders_and_accounts(self):
		roles = {r.role for r in frappe.get_doc("Page", "sp-my-custody").roles}
		self.assertEqual(roles, {"SP Custody Holder", "SP Accountant", "SP Admin", "System Manager"})

	def test_a_user_without_the_role_does_not_get_the_page(self):
		page = frappe.get_doc("Page", "sp-media-library")
		with self.set_user("Guest"):
			self.assertFalse(page.is_permitted())
