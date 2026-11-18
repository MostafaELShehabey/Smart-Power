"""Pump curves (SP-184): a pump covers a duty only inside its curve, read between two points."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_stock.pump_curve import covers, curve_of, head_at
from smart_power.tests.test_prices import make_item
from smart_power.tests.utils import load_erpnext_test_data

load_erpnext_test_data()

CURVE = [{"flow_m3h": 20, "head_m": 110}, {"flow_m3h": 40, "head_m": 70}]


class TestPumpCurve(IntegrationTestCase):
	def test_the_head_is_read_between_two_points(self):
		self.assertEqual(head_at(CURVE, 30), 90)
		self.assertTrue(covers(CURVE, 90, 30))
		self.assertFalse(covers(CURVE, 91, 30))

	def test_the_ends_of_the_curve_count(self):
		self.assertTrue(covers(CURVE, 110, 20))
		self.assertTrue(covers(CURVE, 70, 40))

	def test_nothing_is_read_beyond_the_curve(self):
		self.assertIsNone(head_at(CURVE, 50))
		self.assertFalse(covers(CURVE, 1, 50))
		self.assertFalse(covers(CURVE, 1, 10))

	def test_a_pump_without_a_curve_covers_nothing(self):
		self.assertFalse(covers([], 1, 1))

	def test_a_curve_of_one_point_covers_only_that_flow(self):
		point = [{"flow_m3h": 30, "head_m": 80}]
		self.assertTrue(covers(point, 80, 30))
		self.assertFalse(covers(point, 80, 31))

	def test_the_rows_keep_flow_order_on_the_item(self):
		item = make_item("SP184-ORDER")
		item.set("sp_curve_points", list(reversed(CURVE)))
		item.save()
		self.assertEqual([r.flow_m3h for r in curve_of(item.name)], [20, 40])
		self.assertEqual([r.flow_m3h for r in item.sp_curve_points], [20, 40])
		self.assertTrue(covers(curve_of(item.name), 90, 30))

	def test_the_shut_off_point_at_zero_flow_is_allowed(self):
		item = make_item("SP184-ZERO")
		item.set("sp_curve_points", [{"flow_m3h": 0, "head_m": 130}, *CURVE])
		item.save()
		self.assertEqual(head_at(curve_of(item.name), 0), 130)

	def test_the_same_flow_twice_is_refused(self):
		item = make_item("SP184-TWICE")
		item.set("sp_curve_points", [*CURVE, {"flow_m3h": 20, "head_m": 100}])
		with self.assertRaises(frappe.ValidationError):
			item.save()

	def test_a_negative_point_is_refused(self):
		item = make_item("SP184-NEG")
		item.set("sp_curve_points", [{"flow_m3h": 20, "head_m": -5}])
		with self.assertRaises(frappe.ValidationError):
			item.save()
