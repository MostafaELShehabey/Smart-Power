"""The C3 quote request page is there for the people who take requests (SP-47)."""

import frappe
from frappe.tests import IntegrationTestCase


class TestQuoteRequestPage(IntegrationTestCase):
	def test_page_roles(self):
		roles = {r.role for r in frappe.get_doc("Page", "sp-quote-request").roles}
		self.assertEqual(
			roles,
			{"SP Lead Intake", "SP Customer Followup", "SP Marketing Agent", "SP Admin", "System Manager"},
		)
