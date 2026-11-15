"""Collections CL1 (SP-81): my stations, the empty state, and calls logged on the station."""

import frappe
from frappe.utils import add_days, today

from smart_power.sp_stations import collections
from smart_power.tests.test_installments import InstalmentCase
from smart_power.tests.utils import make_user


class TestCollections(InstalmentCase):
	def setUp(self):
		super().setUp()
		self.hussein = make_user("sp.cl.hussein@example.com", ("customer_followup",))

	def test_my_collections_shows_only_my_stations(self):
		frappe.set_user(self.amira)
		mine = collections.collections()
		self.assertIn(self.station.name, [s["station"] for s in mine["stations"]])
		self.assertFalse(mine["is_admin"])
		row = next(s for s in mine["stations"] if s["station"] == self.station.name)
		self.assertEqual(len(row["schedule"]), 2)
		frappe.set_user(self.hussein)  # no station handed to him: the empty state
		self.assertEqual(collections.collections()["stations"], [])
		with self.assertRaises(frappe.PermissionError):
			collections.log_call(self.station.name, self.call_result())
		frappe.set_user(self.admin)
		everyone = collections.collections(owner=self.amira)
		self.assertTrue(everyone["is_admin"])
		self.assertIn(self.station.name, [s["station"] for s in everyone["stations"]])

	def test_a_call_is_logged_on_the_station_and_is_its_last_contact(self):
		frappe.set_user(self.amira)
		collections.log_call(
			self.station.name, self.call_result(), note="وعد بالدفع", next_call_at=add_days(today(), 1)
		)
		row = next(s for s in collections.collections()["stations"] if s["station"] == self.station.name)
		self.assertEqual(row["last_contact"]["note"], "وعد بالدفع")
		frappe.set_user("Administrator")
		self.assertTrue(
			frappe.db.exists(
				"SP Task",
				{
					"reference_doctype": "SP Station",
					"reference_name": self.station.name,
					"assigned_to": self.amira,
					"status": "Open",
				},
			)
		)
		self.assertEqual(
			frappe.db.get_value("SP Call Log", {"station": self.station.name}, "case"), self.station.case
		)

	def call_result(self) -> str:
		return frappe.db.get_value("SP List Value", {"list_name": "Call Result", "is_active": 1})
