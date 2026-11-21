"""SH1 Showroom sale (SP-102): sold from the showroom store, cash into the box, returns."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, getdate, today

from smart_power.sp_finance import cash_box as cb
from smart_power.sp_finance import centers
from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_sales import showroom_sale as ss
from smart_power.sp_stock import prices
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.test_prices import make_item
from smart_power.tests.utils import load_erpnext_test_data, make_customer, make_user, set_rule, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
BTC_PRICE, BTB_PRICE, COST, STOCK = 1000, 900, 500, 5


class ShowroomCase(IntegrationTestCase):
	"""Each scenario is its own class: the class shares one transaction."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		cls.made = centers.seed_centers(COMPANY)
		set_setting(**{f"center_{k}": v for k, v in cls.made.items()})
		cls.cashier = make_user("sp.shr.cashier@example.com", ("showroom_cashier",))
		cls.item = make_item("SP-SHR-TEST-" + frappe.generate_hash(length=6), is_stock_item=1).name
		prices.set_price(cls.item, prices.BTC, BTC_PRICE)
		prices.set_price(cls.item, prices.BTB, BTB_PRICE)
		cls.store = wh.warehouse_of(COMPANY, wh.SHOWROOM)
		receipt = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": COMPANY,
				"items": [
					{"item_code": cls.item, "qty": STOCK, "t_warehouse": cls.store, "basic_rate": COST}
				],
			}
		).insert()
		receipt.submit()
		cls.profile = ss.seed_pos_profile(COMPANY)
		cls.box = frappe.db.get_value("Account", {"company": COMPANY, "account_name": "Showroom Safe"})
		cls.revenue = frappe.db.get_value("Account", {"company": COMPANY, "account_name": ss.REVENUE_ACCOUNT})

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		if frappe.utils.get_assets_json() is None:  # CI builds no assets; the receipt is printed
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		set_setting(showroom_discount_max_pct=0)
		set_rule("showroom_discount_max", "Warn")
		frappe.defaults.set_user_default("company", COMPANY, self.cashier)  # the key ERPNext reads

	def as_cashier(self, action, *args, **kwargs):
		frappe.set_user(self.cashier)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def sell(self, qty=2, **values):
		return self.as_cashier(
			ss.sell,
			{"items": [{"item_code": self.item, "qty": qty, **values.pop("line", {})}], **values},
		)

	def in_store(self):
		return flt(
			frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": self.store}, "actual_qty")
		)

	def gl(self, account, voucher):
		(net,) = frappe.db.sql(
			"""select coalesce(sum(debit - credit), 0) from `tabGL Entry`
			where account = %s and voucher_no = %s and is_cancelled = 0""",
			(account, voucher),
		)[0]
		return flt(net)


class TestWalkInCashSale(ShowroomCase):
	def test_a_walk_in_cash_sale_is_numbered_and_moves_stock_revenue_and_the_box(self):
		stock, box_sales = self.in_store(), cb.sales_in(self.box, today())
		sale = self.sell(2)
		doc = frappe.get_doc(ss.SI, sale["name"])
		self.assertTrue(doc.name.startswith(f"SHR-{getdate().year}-"))
		self.assertEqual(frappe.db.get_value("Customer", doc.customer, "customer_name"), ss.WALK_IN)
		self.assertEqual(self.in_store(), stock - 2)
		self.assertEqual(self.gl(self.revenue, doc.name), -2 * BTC_PRICE)  # showroom revenue rises
		revenue_center = frappe.db.get_value(
			"GL Entry", {"voucher_no": doc.name, "account": self.revenue}, "cost_center"
		)
		self.assertEqual(revenue_center, self.made["showroom"])
		self.assertEqual(self.gl(self.box, doc.name), 2 * BTC_PRICE)
		self.assertEqual(cb.sales_in(self.box, today()), box_sales + 2 * BTC_PRICE)  # the box's day
		self.assertEqual(doc.owner, self.cashier)
		html = self.as_cashier(ss.receipt, doc.name)
		self.assertIn(doc.name, html)


class TestCompanyPrices(ShowroomCase):
	def test_a_company_customer_buys_at_btb(self):
		customer = make_customer("01012345602", "شركة تجربة المعرض", sp_tier="Company")
		found = self.as_cashier(ss.find_customer, "01012345602")
		self.assertEqual((found["name"], found["price_key"]), (customer, prices.BTB))
		rows = self.as_cashier(ss.find_items, self.item, customer)
		self.assertEqual(rows[0]["price"], BTB_PRICE)
		sale = self.sell(1, customer=customer)
		self.assertEqual(sale["grand_total"], BTB_PRICE)


class TestReturn(ShowroomCase):
	def test_returning_one_item_puts_it_back_and_refunds_from_the_box(self):
		sale = self.sell(2, mode_of_payment="InstaPay")  # a return is refunded in cash all the same
		stock, box_sales = self.in_store(), cb.sales_in(self.box, today())
		ret = self.as_cashier(ss.return_sale, sale["name"], [{"item_code": self.item, "qty": 1}])
		self.assertEqual(ret["refund"], BTC_PRICE)
		self.assertTrue(ret["name"].startswith("SHR-"))
		self.assertEqual(self.in_store(), stock + 1)
		self.assertEqual(self.gl(self.box, ret["name"]), -BTC_PRICE)
		self.assertEqual(cb.sales_in(self.box, today()), box_sales - BTC_PRICE)
		left = self.as_cashier(ss.find_receipt, sale["name"])
		self.assertEqual(left["items"][0]["returnable"], 1)
		with self.assertRaises(frappe.ValidationError):
			self.as_cashier(ss.return_sale, sale["name"], [{"item_code": self.item, "qty": 2}])


class TestDiscount(ShowroomCase):
	def review(self, name):
		return frappe.db.get_value(
			"SP Review Item",
			{"category": "Discount", "reference_doctype": ss.SI, "reference_name": name},
			["amount", "highlight"],
			as_dict=True,
		)

	def test_every_discount_is_listed_with_no_limit_set(self):
		sale = self.sell(1, line={"discount_pct": 10}, discount_amount=50)
		self.assertEqual(sale["grand_total"], BTC_PRICE * 0.9 - 50)
		item = self.review(sale["name"])
		self.assertEqual((flt(item.amount), item.highlight), (150, 0))

	def test_a_discount_above_the_limit_is_highlighted(self):
		set_setting(showroom_discount_max_pct=5)
		sale = self.sell(1, line={"discount_pct": 10})
		self.assertEqual(self.review(sale["name"]).highlight, 1)

	def test_no_discount_no_review(self):
		sale = self.sell(1)
		self.assertIsNone(self.review(sale["name"]))


class TestOtherMethod(ShowroomCase):
	def test_instapay_goes_to_its_official_account_not_the_box(self):
		sale = self.sell(1, mode_of_payment="InstaPay")
		account = ss.mode_account("InstaPay", COMPANY)
		self.assertEqual(self.gl(account, sale["name"]), BTC_PRICE)
		self.assertEqual(self.gl(self.box, sale["name"]), 0)


class TestRefused(ShowroomCase):
	def test_more_than_the_store_holds_and_a_stranger_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.sell(STOCK + 1)
		other = make_user("sp.shr.other@example.com", ("customer_followup",))
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				ss.sell({"items": [{"item_code": self.item, "qty": 1}]})
		finally:
			frappe.set_user("Administrator")
