"""Global search (SP-41): one searchable spelling, then the permission-aware search."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.search import global_search
from smart_power.sp_core.search_key import normalize
from smart_power.tests.utils import load_erpnext_test_data, make_customer, make_user

load_erpnext_test_data()


class TestSearchKey(IntegrationTestCase):
	def test_arabic_written_several_ways_is_one_spelling(self):
		self.assertEqual(normalize("أحمد"), normalize("احمد"))
		self.assertEqual(normalize("إسلام"), normalize("اسلام"))
		self.assertEqual(normalize("فاطمة"), normalize("فاطمه"))
		self.assertEqual(normalize("مصطفى"), normalize("مصطفي"))
		self.assertEqual(normalize("مُحَمَّد"), normalize("محمد"))  # diacritics
		self.assertEqual(normalize("محـــمد"), normalize("محمد"))  # tatweel
		self.assertEqual(normalize("  Smart   POWER "), "smart power")

	def test_a_customer_keeps_its_search_key(self):
		name = make_customer("01007770001", "أحمد عبد الرحمن")
		key = frappe.db.get_value("Customer", name, "sp_search_key")
		self.assertIn("احمد عبد الرحمن", key)
		self.assertIn("01007770001", key)


class TestGlobalSearch(IntegrationTestCase):
	def search_as(self, user, q):
		frappe.set_user(user)
		try:
			return {
				g["doctype"]: [r["name"] for r in g["results"]] for g in global_search(q)["groups"]
			}, global_search(q)
		finally:
			frappe.set_user("Administrator")

	def test_a_name_without_hamza_finds_the_customer_with_it(self):
		name = make_customer("01007770002", "أحمد سعيد البحيري")
		found, _ = self.search_as("Administrator", "احمد سعيد")
		self.assertIn(name, found.get("Customer", []))

	def test_an_exact_number_puts_its_kind_first(self):
		from smart_power.tests.test_quotation_case import case_for_test_customer

		case = case_for_test_customer()
		found, result = self.search_as("Administrator", case.name)
		self.assertEqual(result["groups"][0]["doctype"], "SP Case")
		self.assertEqual(found["SP Case"][0], case.name)
		self.assertEqual(result["groups"][0]["more"]["route"], ["List", "SP Case"])  # show all

	def test_a_colleagues_lead_never_appears(self):
		# كاميليا searches the mobile of مها's (not featured) lead
		maha = make_user("sp.search.maha@example.com", ("marketing_agent", "lead_intake", "quote_creator"))
		camelia = make_user(
			"sp.search.camelia@example.com", ("lead_intake", "customer_followup", "followup_all")
		)
		lead = make_customer("01007770003", "عميل تسويق خاص")
		frappe.db.set_value("Customer", lead, "sp_owner_user", maha)
		found, _ = self.search_as(camelia, "01007770003")
		self.assertNotIn(lead, found.get("Customer", []))
		found, _ = self.search_as(maha, "01007770003")
		self.assertIn(lead, found.get("Customer", []))  # her own
		frappe.db.set_value("Customer", lead, "sp_featured", 1)
		found, _ = self.search_as(camelia, "01007770003")
		self.assertIn(lead, found.get("Customer", []))  # a featured customer is everyone's

	def test_rows_the_user_may_not_read_never_appear(self):
		from smart_power.tests.test_quotation_case import case_for_test_customer

		other = make_user("sp.search.other@example.com", ("lead_intake", "customer_followup"))
		case = case_for_test_customer()  # followed up by someone else
		found, _ = self.search_as(other, case.name)
		self.assertNotIn(case.name, found.get("SP Case", []))

	def test_a_station_number_finds_the_station_first(self):
		from smart_power.sp_sales.quotation import approve_version
		from smart_power.sp_stations.contract import ensure_contract
		from smart_power.sp_stock import warehouses as wh
		from smart_power.tests.utils import make_quotation

		wh.seed_warehouses("_Test Company")
		q = make_quotation(rate=1000, valid_days=3)
		q.submit()
		approve_version(q.name)
		station = ensure_contract(q.sp_case)["station"]
		_found, result = self.search_as("Administrator", station)
		self.assertEqual(result["groups"][0]["doctype"], "SP Station")
		self.assertEqual(result["groups"][0]["results"][0]["name"], station)
