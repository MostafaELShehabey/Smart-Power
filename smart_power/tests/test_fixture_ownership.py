"""Developer fixtures vs the admin's own customizations (SP-164).

These tests use Property Setters and unsaved Custom Fields: inserting a Custom Field alters a
table, which commits the transaction and would leak records between test runs.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.constants import ADMIN_MODULE, SP_MODULES
from smart_power.devtools import fixtures as fx
from smart_power.events.customization import guard_dev_names, tag_admin_owned

ADMIN_CONTEXT = patch("smart_power.events.customization._developer_context", return_value=False)


def _custom_field(fieldname):
	doc = frappe.new_doc("Custom Field")
	doc.update({"dt": "ToDo", "fieldname": fieldname, "label": "Admin Note", "fieldtype": "Data"})
	return doc


def _admin_property_setter(prop="bold"):
	"""What Customize Form writes when the admin changes a field property."""
	with ADMIN_CONTEXT:
		return frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": "DocField",
				"doc_type": "ToDo",
				"field_name": "description",
				"property": prop,
				"property_type": "Check",
				"value": "1",
			}
		).insert(ignore_permissions=True)


class TestFixtureOwnership(IntegrationTestCase):
	def test_admin_record_is_tagged_admin_owned(self):
		ps = _admin_property_setter()
		self.assertEqual(ps.module, ADMIN_MODULE)
		field = _custom_field("custom_admin_note")
		with ADMIN_CONTEXT:
			tag_admin_owned(field)
		self.assertEqual(field.module, ADMIN_MODULE)

	def test_admin_cannot_use_the_developer_prefix(self):
		with ADMIN_CONTEXT, self.assertRaises(frappe.ValidationError):
			tag_admin_owned(_custom_field("sp_admin_tries"))

	def test_admin_cannot_put_a_record_in_a_developer_module(self):
		field = _custom_field("custom_in_dev_module")
		field.module = SP_MODULES[0]
		with ADMIN_CONTEXT, self.assertRaises(frappe.ValidationError):
			tag_admin_owned(field)

	def test_developer_context_is_not_tagged(self):
		field = _custom_field("sp_dev_field")
		field.module = SP_MODULES[0]
		tag_admin_owned(field)  # tests and developer mode count as the developer
		self.assertEqual(field.module, SP_MODULES[0])

	def test_admin_cannot_create_sp_named_roles(self):
		with ADMIN_CONTEXT, self.assertRaises(frappe.ValidationError):
			guard_dev_names(frappe.get_doc({"doctype": "Role", "role_name": "SP Something New"}))
		name = "Site Helper " + frappe.generate_hash(length=6)
		with ADMIN_CONTEXT:
			frappe.get_doc({"doctype": "Role", "role_name": name}).insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Role", name))

	def test_shipped_fixtures_are_all_developer_owned(self):
		for rec in fx.fixture_records():
			if rec["doctype"] in ("Custom Field", "Property Setter"):
				self.assertIn(rec["module"], SP_MODULES, rec["name"])
			if rec["doctype"] == "Custom Field":
				self.assertTrue(rec["fieldname"].startswith("sp_"), rec["name"])
			if rec["doctype"] in ("Role", "Role Profile", "Workflow"):
				self.assertTrue(rec["name"].startswith("SP "), rec["name"])

	def test_preflight_passes_on_a_clean_site(self):
		self.assertEqual(fx.check()["conflicts"], [])

	def test_preflight_stops_a_fixture_that_would_overwrite_an_admin_record(self):
		ps = _admin_property_setter("print_hide")
		fake = {"doctype": "Property Setter", "name": ps.name, "module": SP_MODULES[0]}
		self.assertEqual(len(fx.check([fake])["conflicts"]), 1)
		with patch.object(fx, "fixture_records", return_value=[fake]), self.assertRaises(fx.FixtureConflict):
			fx.preflight()

	def test_preflight_reports_drift_on_developer_records(self):
		rec = next(r for r in fx.fixture_records() if r["doctype"] == "Custom Field")
		later = frappe.utils.add_days(rec["modified"], 1)
		frappe.db.set_value("Custom Field", rec["name"], "description", "edited on the site", modified=later)
		result = fx.check([rec])
		self.assertEqual(result["conflicts"], [])
		self.assertEqual(len(result["drift"]), 1)

	def test_preflight_refuses_unprefixed_role_fixtures(self):
		result = fx.check([{"doctype": "Role", "name": "Sales User"}])
		self.assertEqual(len(result["conflicts"]), 1)

	def test_backup_contains_admin_changes_and_not_developer_ones(self):
		ps = _admin_property_setter("in_list_view")
		data = fx.admin_customizations()
		self.assertIn(ps.name, {r["name"] for r in data["Property Setter"]})
		self.assertNotIn("User-sp_entry_mode", {r["name"] for r in data["Custom Field"]})
		self.assertNotIn("SP Technical Office", {r["name"] for r in data["Role Profile"]})
