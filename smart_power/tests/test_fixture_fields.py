"""Custom field fixtures stay clean (found on the SP-29 / SP-31 forms)."""

import json
import os

import frappe
from frappe.tests import IntegrationTestCase


def fixture_fields():
	path = os.path.join(frappe.get_app_path("smart_power"), "fixtures", "custom_field.json")
	with open(path, encoding="utf-8") as f:
		return json.load(f)


class TestFixtureFields(IntegrationTestCase):
	def test_column_breaks_have_no_label(self):
		# a labelled column break shows a stray heading over the form's right column
		labelled = [
			r["name"] for r in fixture_fields() if r["fieldtype"] == "Column Break" and r.get("label")
		]
		self.assertEqual(labelled, [])

	def test_the_site_has_them_without_labels(self):
		names = [r["name"] for r in fixture_fields() if r["fieldtype"] == "Column Break"]
		labelled = frappe.get_all(
			"Custom Field", {"name": ("in", names), "label": ("is", "set")}, pluck="name"
		)
		self.assertEqual(labelled, [])
