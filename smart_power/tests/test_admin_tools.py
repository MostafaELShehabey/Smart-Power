"""Native admin tools (SP-182): the admin adds a required quote request question for one system
type from a table, a deploy keeps it, his no-code changes are his module's and in the audit log,
and Admin Studio links every tool and the guide."""

import json
import os
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.constants import ADMIN_MODULE
from smart_power.events import customization
from smart_power.sp_core.audit_trail import SENSITIVE
from smart_power.sp_sales import quote_request as qr
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()

LIST_VALUE = "SP List Value"


def system_type(code: str, **values):
	name = frappe.db.get_value(LIST_VALUE, {"list_name": qr.SYSTEM_TYPE_LIST, "code": code})
	if name:
		frappe.delete_doc(LIST_VALUE, name, force=True)
	return frappe.get_doc(
		{"doctype": LIST_VALUE, "list_name": qr.SYSTEM_TYPE_LIST, "code": code, "value_ar": code, **values}
	)


class TestAdminTools(IntegrationTestCase):
	def test_a_required_question_for_one_system_type_comes_from_its_table(self):
		roof = system_type(
			"SP182ROOF",
			request_fields=[
				{"label": "Roof Area", "label_ar": "مساحة السطح", "fieldtype": "Float", "reqd": 1}
			],
		).insert()
		other = system_type("SP182OTHER").insert()
		fields = qr.request_fields(roof.name)
		self.assertEqual(
			[(f["fieldname"], f["fieldtype"], f["reqd"], f["label_ar"]) for f in fields],
			[("roof_area", "Float", 1, "مساحة السطح")],
		)
		self.assertRaises(frappe.MandatoryError, qr.clean_details, roof.name, {})
		self.assertEqual(qr.clean_details(roof.name, {"roof_area": "120"}), {"roof_area": 120.0})
		self.assertEqual(qr.clean_details(other.name, {}), {})  # the other type does not ask it

	def test_a_type_set_up_before_the_table_gets_its_rows(self):
		legacy = [{"fieldname": "well_depth_m", "label": "Well Depth (m)", "fieldtype": "Float", "reqd": 0}]
		doc = system_type("SP182OLD", meta_json=json.dumps({qr.META_KEY: legacy, "other": 1})).insert()
		self.assertEqual(
			[(r.fieldname, r.fieldtype) for r in doc.request_fields], [("well_depth_m", "Float")]
		)
		meta = json.loads(frappe.db.get_value(LIST_VALUE, doc.name, "meta_json"))
		self.assertEqual((meta["other"], meta[qr.META_KEY][0]["fieldname"]), (1, "well_depth_m"))
		doc.reload()
		doc.request_fields[0].label = "Depth"  # a renamed label keeps its field name
		doc.save()
		self.assertEqual(qr.request_fields(doc.name)[0]["fieldname"], "well_depth_m")

	def test_a_bad_row_is_refused(self):
		twice = [{"label": "Area", "fieldtype": "Float"}, {"label": "area", "fieldtype": "Int"}]
		self.assertRaises(frappe.ValidationError, system_type("SP182BAD", request_fields=twice).insert)
		choice = [{"label": "Roof", "fieldtype": "Select"}]
		self.assertRaises(frappe.ValidationError, system_type("SP182SEL", request_fields=choice).insert)

	def test_a_deploy_keeps_the_admins_question(self):
		pump = frappe.db.get_value(LIST_VALUE, {"list_name": qr.SYSTEM_TYPE_LIST, "code": "PUMP"})
		if not pump:
			self.skipTest("the seeded Pump system type is missing")
		doc = frappe.get_doc(LIST_VALUE, pump)
		doc.append("request_fields", {"label": "SP182 Admin Question", "fieldtype": "Data", "reqd": 1})
		doc.save()
		qr.seed_request_fields()  # what a migrate runs
		self.assertIn("sp182_admin_question", [f["fieldname"] for f in qr.request_fields(pump)])

	def test_the_admins_changes_are_his_module_and_in_the_audit_log(self):
		with patch.object(customization, "_developer_context", return_value=False):
			setter = frappe.get_doc(
				{
					"doctype": "Property Setter",
					"doctype_or_field": "DocField",
					"doc_type": "Customer",
					"field_name": "customer_name",
					"property": "bold",
					"property_type": "Check",
					"value": "1",
				}
			).insert()
		self.assertEqual(setter.module, ADMIN_MODULE)  # never exported, so a deploy keeps it
		self.assertTrue(
			{"Custom Field", "Property Setter", "Workflow", "Print Format", "Notification", "Report"}
			<= set(SENSITIVE)
		)

	def test_admin_studio_links_the_tools_and_the_guide(self):
		path = os.path.join(
			frappe.get_app_path("smart_power"), "sp_core", "sidebar", "admin_studio", "admin_studio.json"
		)
		with open(path) as f:
			links = {(i["link_type"], i["link_to"]) for i in json.load(f)["items"] if i.get("type") == "Link"}
		tools = {
			("Page", "sp-admin-guide"),
			("DocType", "Customize Form"),
			("DocType", "Workflow"),
			("Page", "print-format-builder"),
			("DocType", "Notification"),
			("DocType", "Report"),
			("Page", "permission-manager"),
			("DocType", "User Permission"),
			("DocType", "Smart Power Settings"),
			("DocType", "SP Rule Setting"),
		}
		self.assertTrue(tools <= links, tools - links)
		for kind, name in links:
			self.assertTrue(frappe.db.exists(kind, name), f"{kind} {name}")
		roles = set(
			frappe.get_all("Has Role", {"parent": "sp-admin-guide", "parenttype": "Page"}, pluck="role")
		)
		self.assertEqual(roles, {"SP Admin", "System Manager"})
