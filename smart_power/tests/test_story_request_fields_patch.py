"""The story's request fields replace the earlier proposal, but never the admin's (SP-47)."""

import json

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.patches import sp47_story_request_fields as patch

PUMP = "System Type-PUMP"


def set_fields(fields):
	frappe.db.set_value(
		"SP List Value", PUMP, "meta_json", json.dumps({"request_fields": fields}, ensure_ascii=False)
	)


def fieldnames():
	raw = frappe.db.get_value("SP List Value", PUMP, "meta_json")
	return [f["fieldname"] for f in json.loads(raw)["request_fields"]]


class TestStoryRequestFieldsPatch(IntegrationTestCase):
	def test_earlier_proposal_is_replaced(self):
		set_fields(patch.EARLIER_PROPOSAL["PUMP"])
		patch.execute()
		self.assertEqual(fieldnames(), ["hp", "well_depth_m", "water_level_m", "pump_depth_m"])

	def test_admins_own_fields_are_kept(self):
		set_fields([{"fieldname": "custom_x", "fieldtype": "Data"}])
		patch.execute()
		self.assertEqual(fieldnames(), ["custom_x"])
