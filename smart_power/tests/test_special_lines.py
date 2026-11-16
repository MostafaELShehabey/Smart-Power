"""Special quote lines (SP-58): manual, merge for printing, winch, hidden station commission."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_quotes.quote_print import print_lines
from smart_power.sp_quotes.special_lines import service_items
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"
COMMISSION, WINCH_AMOUNT = 5000, 3000
ELECTRICAL = "أعمال كهربائية"


class TestSpecialLines(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		frappe.db.delete("Item", {"item_code": ("in", tuple(service_items().values()))})  # made on use

	def setUp(self):
		self.amira = make_user("sp.sl.amira@example.com", ("project_manager", "contract_manager"))

	def tearDown(self):
		frappe.set_user("Administrator")

	def quote(self, *rows):
		q = make_quotation(rate=100000, save=False)
		q.items[0].sp_cost = 70000
		for row in rows:
			q.append("items", row)
		return q.insert()

	def test_the_commission_is_not_printed_nor_in_the_total_but_lowers_the_profit(self):
		plain = self.quote()
		q = self.quote(
			{"sp_line_kind": "Commission", "item_name": "عمولة المهندس", "qty": 1, "rate": COMMISSION}
		)
		row = q.items[-1]
		self.assertEqual((row.item_code, row.sp_is_hidden), (service_items()["Commission"], 1))
		self.assertEqual((flt(row.rate), flt(row.sp_cost)), (0, COMMISSION))  # cost only
		self.assertEqual(flt(q.grand_total), flt(plain.grand_total))  # the customer total is unchanged
		self.assertEqual(flt(q.sp_total_cost), flt(plain.sp_total_cost) + COMMISSION)
		self.assertEqual(flt(q.sp_profit), flt(plain.sp_profit) - COMMISSION)
		self.assertNotIn("عمولة المهندس", [line["description"] for line in print_lines(q.items, names={})])

	def test_three_merged_lines_print_as_one_with_their_total(self):
		q = self.quote(
			*(
				{
					"item_code": "_Test Item 2",
					"item_name": name,
					"qty": 1,
					"rate": rate,
					"sp_merge_group": ELECTRICAL,
				}
				for name, rate in (("كابل", 1200), ("قاطع", 800), ("لوحة توزيع", 1500))
			)
		)
		lines = print_lines(q.items, names={})
		merged = [line for line in lines if line["description"] == ELECTRICAL]
		self.assertEqual(len(merged), 1)
		self.assertEqual((merged[0]["qty"], flt(merged[0]["amount"])), (1, 3500))
		self.assertEqual(len(lines), 2)  # the main line and the merged one; the rows themselves stay
		self.assertEqual(len(q.items), 4)

	def test_a_manual_line_keeps_its_own_text(self):
		q = self.quote(
			{"sp_line_kind": "Manual", "item_name": "نقل لموقع بعيد", "qty": 1, "rate": 2500, "sp_cost": 1800}
		)
		row = q.items[-1]
		self.assertEqual((row.item_code, row.item_name), (service_items()["Manual"], "نقل لموقع بعيد"))
		self.assertEqual((flt(row.amount), flt(row.sp_line_profit)), (2500, 700))
		printed = [line["description"] for line in print_lines(q.items)]  # with the items' Arabic names
		self.assertIn("نقل لموقع بعيد", printed)

	def test_the_winch_line_becomes_an_expected_winch_job_on_the_contract(self):
		q = self.quote(
			{"sp_line_kind": "Winch", "qty": 1, "rate": WINCH_AMOUNT},
			{"sp_line_kind": "Commission", "qty": 1, "sp_cost": COMMISSION},
		)
		q.submit()
		approve_version(q.name)
		frappe.set_user(self.amira)
		result = make_contract(q.sp_case)
		frappe.set_user("Administrator")
		station = frappe.get_doc("SP Station", result["station"])
		self.assertEqual(
			(flt(station.winch_expected_amount), station.winch_status), (WINCH_AMOUNT, "Expected")
		)
		self.assertEqual(flt(station.commission_amount), COMMISSION)  # carried to the contract
		so = frappe.get_doc("Sales Order", result["sales_order"])
		codes = [r.item_code for r in so.items]
		self.assertIn(service_items()["Winch"], codes)  # the customer pays the winch
		self.assertNotIn(service_items()["Commission"], codes)  # the commission never reaches him
		self.assertEqual(flt(so.sp_referrer_commission), COMMISSION)
