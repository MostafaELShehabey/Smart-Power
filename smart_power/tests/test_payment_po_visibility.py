"""Customer payments by recorder and collector; supplier rates on POs for the buying roles (SP-35)."""

import frappe
from frappe.client import get as rest_get
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from smart_power.permissions import sync_cost_permissions
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import ensure_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_customer_payment import account
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"
SUPPLIER_RATE = 4321


def as_user(user, fn):
	frappe.set_user(user)
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")


class TestPaymentVisibility(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)

	def setUp(self):
		self.collector = make_user("sp.pv.collector@example.com", ("collection_officer",))
		self.other = make_user("sp.pv.other@example.com", ("collection_officer",))
		self.cashier = make_user("sp.pv.cashier@example.com", ("showroom_cashier",))
		q = make_quotation(rate=50000, valid_days=3)
		q.submit()
		approve_version(q.name)
		self.station = ensure_contract(q.sp_case)["station"]
		frappe.db.set_value("SP Station", self.station, "collection_owner", self.collector)
		cash = account("SP PV Cash", "Cash", "Official", account_type="Cash")
		self.payment = as_user(
			self.cashier,
			lambda: frappe.get_doc(
				{
					"doctype": "SP Customer Payment",
					"station": self.station,
					"amount": 1000,
					"work_date": today(),
					"method": "Payment Method-CASH",
					"receiving_account": cash,
					"receipt_photo": "/files/receipt.jpg",
				}
			).insert(),
		).name

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_payment_is_seen_by_its_recorder_its_collector_and_the_admin(self):
		listed = lambda user: as_user(user, lambda: frappe.get_list("SP Customer Payment", pluck="name"))  # noqa: E731
		self.assertIn(self.payment, listed(self.cashier))  # she recorded it
		self.assertIn(self.payment, listed(self.collector))  # he collects the station
		self.assertNotIn(self.payment, listed(self.other))
		self.assertFalse(frappe.has_permission("SP Customer Payment", "read", self.payment, user=self.other))


class TestPurchaseOrderRates(IntegrationTestCase):
	def setUp(self):
		sync_cost_permissions()
		self.amira = make_user("sp.po.amira@example.com", ("purchase_officer",))
		self.keeper = make_user("sp.po.keeper@example.com", ("main_store_keeper", "receipt_confirmer"))
		from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order

		self.po = create_purchase_order(rate=SUPPLIER_RATE, qty=2)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_only_the_buying_roles_see_supplier_rates(self):
		seen = as_user(self.amira, lambda: rest_get("Purchase Order", self.po.name))
		self.assertEqual(seen["items"][0]["rate"], SUPPLIER_RATE)
		self.assertEqual(seen["grand_total"], SUPPLIER_RATE * 2)
		hidden = as_user(self.keeper, lambda: rest_get("Purchase Order", self.po.name))
		self.assertEqual(hidden["items"][0]["qty"], 2)  # what to receive, not what it cost
		self.assertFalse(hidden["items"][0]["rate"])
		self.assertFalse(hidden["grand_total"])
