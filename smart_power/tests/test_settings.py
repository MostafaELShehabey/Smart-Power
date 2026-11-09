"""Smart Power Settings: seed values, validation, change log and lookups."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.services import settings as sps
from smart_power.sp_core.setup.seed import defaults, seed_settings
from smart_power.tests.utils import set_setting


class TestSmartPowerSettings(IntegrationTestCase):
	def test_seed_fills_only_empty_values(self):
		set_setting(validity_days=9)
		seed_settings()
		doc = frappe.get_single("Smart Power Settings")
		self.assertEqual(doc.validity_days, 9)
		self.assertEqual(doc.quote_due_hours, defaults()["settings"]["quote_due_hours"]["value"])

	def test_min_above_max_is_refused(self):
		doc = frappe.get_single("Smart Power Settings")
		doc.append("margin_ranges", {"scope": "Supply only", "min_pct": 9, "max_pct": 6})
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_negative_number_is_refused(self):
		doc = frappe.get_single("Smart Power Settings")
		doc.field_entry_lock_days = -1
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_every_change_is_logged(self):
		before = frappe.db.count("Version", {"ref_doctype": "Smart Power Settings"})
		doc = frappe.get_single("Smart Power Settings")
		doc.case_inactivity_days = (doc.case_inactivity_days or 0) + 1
		doc.save(ignore_version=False)  # tests skip versions unless asked
		self.assertEqual(frappe.db.count("Version", {"ref_doctype": "Smart Power Settings"}), before + 1)

	def test_margin_range_picks_the_most_specific_row(self):
		pump = frappe.db.get_value("SP List Value", {"list_name": "System Type", "code": "PUMP"})
		doc = frappe.get_single("Smart Power Settings")
		doc.set(
			"margin_ranges",
			[
				{"scope": "Supply and install", "min_pct": 9, "max_pct": 11},
				{"offer_type": pump, "scope": "Supply and install", "min_pct": 12, "max_pct": 15},
				{"offer_type": pump, "min_pct": 5, "max_pct": 20},
			],
		)
		doc.save()
		self.assertEqual(sps.margin_range(pump, "Supply and install").min_pct, 12)
		self.assertEqual(sps.margin_range(pump, "Supply only").min_pct, 5)
		self.assertEqual(sps.margin_range("other", "Supply and install").min_pct, 9)
		self.assertIsNone(sps.margin_range("other", "Supply only"))


class TestListValues(IntegrationTestCase):
	def test_seeded_system_types(self):
		codes = set(frappe.get_all("SP List Value", {"list_name": "System Type"}, pluck="code"))
		self.assertTrue({"PUMP", "CHASSIS", "OFFGRID", "ONGRID", "HYBRID"} <= codes)

	def test_code_is_unique_within_a_list(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "SP List Value", "list_name": "System Type", "code": "pump", "value_ar": "مكرر"}
			).insert()
		# the same code in another list is fine
		frappe.get_doc(
			{"doctype": "SP List Value", "list_name": "Region", "code": "PUMP", "value_ar": "منطقة"}
		).insert()
