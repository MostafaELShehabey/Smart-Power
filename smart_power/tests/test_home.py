"""G2 Home (SP-38): my cards by role, the filtered list behind each, and my queue."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_to_date, now_datetime, today

from smart_power.dashboards import cards, queue
from smart_power.sp_finance import centers
from smart_power.sp_finance.accounts import holder_account, seed_accounts
from smart_power.tests.test_case import make_case
from smart_power.tests.test_transit import journal
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_rule, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"


def home_of(user: str) -> dict:
	frappe.cache.delete_value(f"sp_home_cards:{user}")  # the one-minute cache
	frappe.set_user(user)
	try:
		return {c["key"]: c for c in cards.get_home()["cards"]}
	finally:
		frappe.set_user("Administrator")


class TestHome(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)

	def setUp(self):
		set_setting(quote_due_hours=24, quote_amber_hours=18)
		self.aya = make_user("sp.home.aya@example.com", ("quote_creator",))
		self.hussein = make_user("sp.home.hussein@example.com", ("showroom_sales", "showroom_cashier"))

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_requests_waiting_shows_the_count_in_red_with_the_oldest(self):
		before = home_of(self.aya)["requests_waiting"]["value"]
		for hours in (26, 5, 1):  # sp-allow-number: the acceptance check's 3 requests, the oldest 26 h
			case = make_case(status="Quote request")
			frappe.db.set_value(
				"SP Case",
				case.name,
				"creation",
				add_to_date(now_datetime(), hours=-hours),
				update_modified=False,
			)
		card = home_of(self.aya)["requests_waiting"]
		self.assertEqual(card["value"], before + 3)
		self.assertEqual(card["indicator"], "red")
		self.assertEqual(card["note"], "Oldest: 26 h")  # أقدم: 26 س in Arabic
		self.assertEqual(card["route"], ["sp-quote-queue"])  # the click opens the queue

	def test_a_card_opens_its_list_with_the_same_filter(self):
		intake = make_user("sp.home.intake@example.com", ("lead_intake", "customer_followup"))
		make_case(status="Quote request", requested_by=intake)
		card = home_of(intake)["my_requests_waiting"]
		self.assertGreaterEqual(card["value"], 1)
		self.assertEqual(card["route"], ["List", "SP Case"])
		filters = card["route_options"]
		frappe.set_user(intake)
		listed = frappe.get_list("SP Case", filters=filters, pluck="name")
		frappe.set_user("Administrator")
		self.assertEqual(len(listed), card["value"])  # the list holds what the card counts

	def test_cash_held_past_the_limit_is_red(self):
		made = centers.seed_centers(COMPANY)
		set_setting(cash_held_limit_days=3, **{f"center_{k}": v for k, v in made.items()})
		set_rule("cash_held_too_long", "Warn", warn_needs_reason=0)
		self.assertNotIn("cash_on_hand", home_of(self.hussein))  # no cash account: no card
		cash = holder_account(self.hussein, "Transit", COMPANY)
		receivable = frappe.get_cached_value("Company", COMPANY, "default_receivable_account")
		journal(cash, receivable, 700, add_days(today(), -4))
		card = home_of(self.hussein)["cash_on_hand"]
		self.assertEqual((card["value"], card["fieldtype"], card["indicator"]), (700, "Currency", "red"))

	def test_my_queue_merges_tasks_and_todos_high_first(self):
		from smart_power.sp_core.inbox import create_task

		create_task("Other", "User", "Guest", self.aya, "مهمة عادية")
		create_task("Other", "User", self.aya, self.aya, "مهمة عاجلة", priority="High")
		frappe.get_doc(
			{"doctype": "ToDo", "allocated_to": self.aya, "description": "تذكير يدوي", "date": today()}
		).insert(ignore_permissions=True)
		frappe.set_user(self.aya)
		rows = queue.get_my_queue()
		frappe.set_user("Administrator")
		titles = [r["title"] for r in rows]
		self.assertEqual(titles[0], "مهمة عاجلة")
		self.assertTrue({"مهمة عادية", "تذكير يدوي"} <= set(titles))


class TestRoleCards(IntegrationTestCase):
	def test_every_profile_gets_its_cards_and_each_card_opens_somewhere(self):
		from smart_power.sp_core.setup.role_catalogue import PROFILES

		for profile in PROFILES:
			if not any(cards.variants_of_roles(profile.roles())):
				continue
			user = make_user(f"sp.home.{profile.name.lower().replace(' ', '.')}@example.com", profile.keys)
			home = home_of(user)
			self.assertTrue(home, profile.name)
			for key, c in home.items():
				self.assertTrue(c.get("route"), (profile.name, key))
				self.assertIn(c["indicator"], ("red", "orange", "green", "gray"), (profile.name, key))

	def test_each_variant_sees_its_own_cards(self):
		finance = home_of(make_user("sp.home.finance@example.com", ("accountant",)))
		self.assertTrue({"waiting_confirmation", "cash_in_transit", "bounced_cheques"} <= set(finance))
		self.assertNotIn("requests_waiting", finance)
		store = home_of(make_user("sp.home.store@example.com", ("main_store_keeper",)))
		self.assertIn("consignment_low", store)
		self.assertNotIn("waiting_confirmation", store)
		projects = home_of(make_user("sp.home.projects@example.com", ("project_manager",)))
		self.assertTrue({"waiting_contract", "open_stations", "overdue_installments"} <= set(projects))
